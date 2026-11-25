"""3단계 배포 도구 — Cloud Run + IAP. 내 PC 의 가상환경에서 실행 (gcloud 로그인 필요).

    python scripts/deploy.py setup  --project v12-2027     # 처음 한 번: API 켜기, 서비스 계정·권한
    python scripts/deploy.py deploy --project v12-2027     # 배포 (코드 바꿀 때마다 다시 실행)
    python scripts/deploy.py grant  --project v12-2027 --member user:someone@ubase.co.kr --role manager
    python scripts/deploy.py grant  --project v12-2027 --file access/managers.txt --role manager   # 명단 한 번에
    python scripts/deploy.py grant  --project v12-2027 --member group:agent360-users@ubase.co.kr
    python scripts/deploy.py url    --project v12-2027     # 접속 주소 보기
    python scripts/deploy.py ai-access --project v12-2027  # 앱 계정이 기존 데이터 에이전트(v11-2026)를 쓰게 권한 주기
    python scripts/deploy.py kpi-pipeline --project v12-2027  # KPI 매일 갱신 예약 쿼리 (v11 Dynamic → v12 kpi)

공통 옵션: --region asia-northeast3 --service agent360 --dry-run(실행 없이 명령만 출력)
접속 허용(grant)은 '들어올 수 있는 사람', 앱 안의 역할·팀은 bq_setup.py user 로 따로 등록한다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APIS = ["run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
        "iap.googleapis.com", "bigquery.googleapis.com"]


class Runner:
    def __init__(self, dry: bool):
        self.dry = dry

    def __call__(self, args: list[str], *, ok_fail: bool = False, capture: bool = False) -> str:
        line = subprocess.list2cmdline(args)
        print(f"\n$ {line}")
        if self.dry:
            return "PROJECT_NUMBER" if capture else ""
        # Windows 에서 gcloud 는 gcloud.cmd 라 셸을 거쳐야 실행된다
        r = subprocess.run(line if os.name == "nt" else args, shell=(os.name == "nt"), cwd=ROOT,
                           text=True, capture_output=capture)
        if r.returncode != 0 and not ok_fail:
            if capture and r.stderr:
                print(r.stderr)
            sys.exit(f"❌ 실패했습니다 (위 메시지 확인). 명령: {line}")
        return (r.stdout or "").strip() if capture else str(r.returncode)


def sa_email(a) -> str:
    return f"{a.service}-run@{a.project}.iam.gserviceaccount.com"


def project_number(run: Runner, a) -> str:
    return run(["gcloud", "projects", "describe", a.project, "--format=value(projectNumber)"], capture=True)


def cmd_setup(run: Runner, a):
    num = project_number(run, a)
    run(["gcloud", "services", "enable", *APIS, f"--project={a.project}"])
    run(["gcloud", "iam", "service-accounts", "create", f"{a.service}-run",
         "--display-name=Agent360 Cloud Run", f"--project={a.project}"], ok_fail=True)   # 이미 있으면 통과
    run(["gcloud", "projects", "add-iam-policy-binding", a.project,
         f"--member=serviceAccount:{sa_email(a)}", "--role=roles/bigquery.jobUser", "--condition=None", "--quiet"])
    # 소스 배포(Cloud Build)가 쓰는 기본 계정 — 새 프로젝트는 이 권한이 없어 빌드가 실패하는 경우가 있다
    run(["gcloud", "projects", "add-iam-policy-binding", a.project,
         f"--member=serviceAccount:{num}-compute@developer.gserviceaccount.com",
         "--role=roles/run.builder", "--condition=None", "--quiet"])
    run(["gcloud", "beta", "services", "identity", "create", "--service=iap.googleapis.com",
         f"--project={a.project}"], ok_fail=True)
    grant_datasets(a)
    print("\n✅ setup 완료 — 다음: python scripts\\deploy.py deploy --project", a.project)


def grant_datasets(a):
    """앱 계정: common·capacity·kpi 는 읽기, agent360·roster 는 읽기·쓰기(코칭·신호·감사 로그·변경 기록 / 명단 버전·초안)."""
    grants = [(a.common, "roles/bigquery.dataViewer"), (a.module, "roles/bigquery.dataEditor"),
              ("capacity", "roles/bigquery.dataViewer"), ("roster", "roles/bigquery.dataEditor"),
              ("kpi", "roles/bigquery.dataViewer")]
    for ds, role in grants:
        sql = f'GRANT `{role}` ON SCHEMA `{a.project}.{ds}` TO "serviceAccount:{sa_email(a)}"'
        print(f"\n$ (BigQuery) {sql}")
        if a.dry_run:
            continue
        from google.cloud import bigquery
        bigquery.Client(project=a.project, location=a.region).query(sql).result()


def env_vars(a) -> str:
    v = ["ENV=prod", "DATA_BACKEND=bigquery", f"GCP_PROJECT={a.project}", f"BQ_LOCATION={a.region}",
         f"COMMON_DATASET={a.common}", f"MODULE_DATASET={a.module}", f"ALLOWED_DOMAINS={a.domain}"]
    if a.agent_id:
        v += [f"AI_AGENT_PROJECT={a.agent_project}", "AI_AGENT_LOCATION=global", f"AI_AGENT_ID={a.agent_id}",
              f"AI_QUOTA_PROJECT={a.agent_project}"]
    return ",".join(v)


def cmd_ai_access(run: Runner, a):
    """앱 서비스 계정이 기존 데이터 에이전트를 쓰도록 에이전트 프로젝트에 최소 권한을 준다 (그 프로젝트 소유자가 실행)."""
    p, sa = a.agent_project, sa_email(a)
    run(["gcloud", "services", "enable", "geminidataanalytics.googleapis.com", "cloudaicompanion.googleapis.com",
         f"--project={p}"])
    for role in ("roles/geminidataanalytics.dataAgentUser", "roles/bigquery.jobUser",
                 "roles/serviceusage.serviceUsageConsumer", "roles/cloudaicompanion.user"):
        run(["gcloud", "projects", "add-iam-policy-binding", p, f"--member=serviceAccount:{sa}",
             f"--role={role}", "--condition=None", "--quiet"])
    for ds in [d.strip() for d in a.agent_datasets.split(",") if d.strip()]:
        sql = f'GRANT `roles/bigquery.dataViewer` ON SCHEMA `{p}.{ds}` TO "serviceAccount:{sa}"'
        print(f"\n$ (BigQuery) {sql}")
        if not a.dry_run:
            from google.cloud import bigquery
            bigquery.Client(project=p, location=a.region).query(sql).result()
    print(f"\n✅ AI 권한 완료 ({p}: 에이전트 사용·쿼리 실행, 데이터셋 {a.agent_datasets} 읽기)."
          f"\n   다음: python scripts\\deploy.py deploy --project {a.project}  (AI 설정이 들어간 채로 다시 배포)")


KPI_SA = "kpi-pipeline"
KPI_JOB = "KPI 매일 갱신 (v11 Dynamic → kpi)"


def _bq_grant(a, project: str, sql: str):
    print(f"\n$ (BigQuery) {sql}")
    if not a.dry_run:
        from google.cloud import bigquery
        bigquery.Client(project=project, location=a.region).query(sql).result()


def _dts(run: Runner, method: str, url: str, body: dict | None = None) -> dict:
    """BigQuery Data Transfer REST (bq CLI 없이)."""
    import json
    import urllib.request
    print(f"\n$ ({method}) {url}")
    if run.dry:
        return {}
    token = run(["gcloud", "auth", "print-access-token"], capture=True)
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or b"{}")


def cmd_kpi_pipeline(run: Runner, a):
    """KPI 매일 갱신: 전용 서비스 계정(kpi-pipeline@)으로 매일 11:00(KST) 예약 쿼리 실행.
    그 계정 권한 = v12 쿼리 실행 + kpi 데이터세트 쓰기 + v11-2026.Dynamic 읽기. 이미 있으면 쿼리·시간만 고친다."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from bq_setup import kpi_refresh_sql
    sa = f"{KPI_SA}@{a.project}.iam.gserviceaccount.com"
    run(["gcloud", "services", "enable", "bigquerydatatransfer.googleapis.com", f"--project={a.project}"])
    run(["gcloud", "iam", "service-accounts", "create", KPI_SA, "--display-name=KPI daily refresh",
         f"--project={a.project}"], ok_fail=True)
    run(["gcloud", "projects", "add-iam-policy-binding", a.project, f"--member=serviceAccount:{sa}",
         "--role=roles/bigquery.jobUser", "--condition=None", "--quiet"])
    # 예약 쿼리 서비스(DTS 서비스 에이전트)가 이 계정으로 실행할 수 있게 — 이 계정 하나에만
    num = project_number(run, a)
    run(["gcloud", "iam", "service-accounts", "add-iam-policy-binding", sa,
         f"--member=serviceAccount:service-{num}@gcp-sa-bigquerydatatransfer.iam.gserviceaccount.com",
         "--role=roles/iam.serviceAccountTokenCreator", f"--project={a.project}", "--quiet"])
    _bq_grant(a, a.project, f'GRANT `roles/bigquery.dataEditor` ON SCHEMA `{a.project}.kpi` TO "serviceAccount:{sa}"')
    _bq_grant(a, a.agent_project,
              f'GRANT `roles/bigquery.dataViewer` ON SCHEMA `{a.agent_project}.Dynamic` TO "serviceAccount:{sa}"')
    base = f"https://bigquerydatatransfer.googleapis.com/v1/projects/{a.project}/locations/{a.region}/transferConfigs"
    body = {"displayName": KPI_JOB, "dataSourceId": "scheduled_query", "schedule": "every day 02:00",   # UTC = 11:00 KST
            "params": {"query": kpi_refresh_sql(a.project, a.kpi_days)}}
    found = [c for c in _dts(run, "GET", f"{base}?dataSourceIds=scheduled_query").get("transferConfigs", [])
             if c.get("displayName") == KPI_JOB]
    if found:
        out = _dts(run, "PATCH", f"https://bigquerydatatransfer.googleapis.com/v1/{found[0]['name']}"
                   f"?updateMask=params,schedule&serviceAccountName={sa}", body)
    else:
        out = _dts(run, "POST", f"{base}?serviceAccountName={sa}", body)
    print(f"\n✅ 예약 쿼리 {'수정' if found else '생성'}: {out.get('name', '(dry-run)')} · 다음 실행 {out.get('nextRunTime', '')}")


def cmd_deploy(run: Runner, a):
    num = project_number(run, a)
    run(["gcloud", "run", "deploy", a.service, "--source=.", f"--region={a.region}", f"--project={a.project}",
         "--no-allow-unauthenticated", f"--service-account={sa_email(a)}", f"--set-env-vars={env_vars(a)}",
         "--memory=512Mi", "--cpu=1", "--min-instances=0", "--max-instances=3", "--timeout=300", "--quiet"])
    enable_iap(run, a)
    # IAP 가 서비스를 호출할 수 있게
    run(["gcloud", "run", "services", "add-iam-policy-binding", a.service, f"--region={a.region}",
         f"--project={a.project}", f"--member=serviceAccount:service-{num}@gcp-sa-iap.iam.gserviceaccount.com",
         "--role=roles/run.invoker", "--quiet"])
    cmd_url(run, a)
    print("\n✅ 배포 완료 — 접속 허용: python scripts\\deploy.py grant --project", a.project, "--member user:이메일")


def enable_iap(run: Runner, a):
    """IAP 켜기 (gcloud 버전에 따라 beta 에만 있을 수 있음)."""
    upd = ["run", "services", "update", a.service, f"--region={a.region}", f"--project={a.project}", "--iap", "--quiet"]
    if run(["gcloud", *upd], ok_fail=True) not in ("0", ""):
        run(["gcloud", "beta", *upd])


def service_annotations(run: Runner, a) -> str | None:
    """서비스가 없거나 Cloud Run API 가 꺼져 있으면 None."""
    out = run(["gcloud", "run", "services", "describe", a.service, f"--region={a.region}",
               f"--project={a.project}", "--format=value(metadata.annotations)"], capture=True, ok_fail=True)
    return out if out and "ERROR" not in out else None


def iap_enabled(run: Runner, a) -> bool:
    return "iap-enabled=true" in (service_annotations(run, a) or "").replace(" ", "").lower()


def read_members(a) -> list[str]:
    """--member 하나 또는 --file 명단(한 줄에 하나, # 주석·빈 줄 무시). 'user:' 접두어는 없으면 붙인다."""
    raw = [a.member] if a.member else []
    if a.file:
        for line in Path(a.file).read_text(encoding="utf-8-sig").splitlines():
            line = line.split("#", 1)[0].strip().strip(",;")
            if line:
                raw.append(line)
    if not raw:
        sys.exit("--member 또는 --file 을 주세요")
    members, bad = [], []
    for m in raw:
        m = m.strip().lower()
        m = m if ":" in m else f"user:{m}"
        if not m.endswith("@" + a.domain) or m.count("@") != 1:
            bad.append(m)
        elif m not in members:
            members.append(m)
    if bad:
        sys.exit(f"@{a.domain} 계정·그룹만 허용합니다. 확인할 항목: {', '.join(bad)}")
    return members


def register_roles(a, emails: list[str]):
    """앱 안 역할을 한 번에 등록/갱신 (agent360.user_roles MERGE)."""
    teams = [t.strip() for t in (a.teams or "").split(",") if t.strip()]
    sql = f"""MERGE `{a.project}.{a.module}.user_roles` t
USING (SELECT LOWER(e) email, SPLIT(LOWER(e), '@')[OFFSET(0)] name FROM UNNEST(@emails) e) s
ON LOWER(t.email) = s.email
WHEN MATCHED THEN UPDATE SET role = @role, teams = @teams, active = TRUE,
  updated_at = CURRENT_TIMESTAMP(), updated_by = 'deploy.grant'
WHEN NOT MATCHED THEN INSERT (email, name, role, teams, active, updated_at, updated_by)
  VALUES (s.email, s.name, @role, @teams, TRUE, CURRENT_TIMESTAMP(), 'deploy.grant')"""
    print(f"\n$ (BigQuery) user_roles ← {len(emails)}명 role={a.role} teams={teams or '(전체)'}")
    if a.dry_run:
        print(sql)
        return
    from google.cloud import bigquery
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("emails", "STRING", emails),
        bigquery.ScalarQueryParameter("role", "STRING", a.role),
        bigquery.ArrayQueryParameter("teams", "STRING", teams),
    ])
    bigquery.Client(project=a.project, location=a.region).query(sql, job_config=cfg).result()


def cmd_grant(run: Runner, a):
    members = read_members(a)
    if a.role and a.role not in ("admin", "manager", "sv", "viewer"):
        sys.exit("--role 은 admin | manager | sv | viewer")
    if a.role in ("sv", "viewer") and not a.teams:
        sys.exit(f"--role {a.role} 은 --teams 가 필요합니다 (예: --teams R1-A,R1-B)")
    if not a.dry_run and service_annotations(run, a) is None:
        sys.exit(f"❌ Cloud Run 서비스 '{a.service}' 가 아직 없습니다 (또는 Cloud Run API 가 꺼져 있음).\n"
                 f"   먼저 순서대로 실행하세요:\n"
                 f"   python scripts\\deploy.py setup  --project {a.project}\n"
                 f"   python scripts\\deploy.py deploy --project {a.project}")
    if not a.dry_run and not iap_enabled(run, a):
        print("\nℹ️ 서비스에 IAP 가 아직 꺼져 있어 먼저 켭니다.")
        enable_iap(run, a)
    failed = []
    for n, m in enumerate(members, 1):
        print(f"\n[{n}/{len(members)}] {m}")
        cmd = ["gcloud", "iap", "web", "add-iam-policy-binding", f"--member={m}",
               "--role=roles/iap.httpsResourceAccessor", f"--region={a.region}", "--resource-type=cloud-run",
               f"--service={a.service}", f"--project={a.project}", "--condition=None", "--quiet"]
        for i in range(4):   # IAP 를 막 켠 직후·동시 수정 시 500/409 가 잠시 날 수 있다
            if run(cmd, ok_fail=True) in ("0", ""):
                break
            if i == 3:
                failed.append(m)
                break
            print(f"⏳ 잠시 뒤 다시 시도합니다 ({i + 1}/3)")
            time.sleep(30)
    ok = [m for m in members if m not in failed]
    users = [m.split(":", 1)[1] for m in ok if m.startswith("user:")]
    if a.role and users:
        register_roles(a, users)
    print(f"\n✅ 접속 허용 {len(ok)}명" + (f" · 앱 역할 {a.role} 등록 {len(users)}명" if a.role and users else ""))
    if failed:
        print("❌ 실패 (다시 실행하면 이 사람들만 다시 시도해도 됨):\n   " + "\n   ".join(failed))
        sys.exit(1)
    if not a.role:
        print("ℹ️ 앱 역할도 필요합니다: 같은 명령에 --role manager (또는 sv/viewer --teams …) 를 붙여 다시 실행")


def cmd_url(run: Runner, a):
    url = run(["gcloud", "run", "services", "describe", a.service, f"--region={a.region}",
               f"--project={a.project}", "--format=value(status.url)"], capture=True)
    print(f"\n🔗 접속 주소: {url}/agent360")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "deploy", "grant", "url", "ai-access", "kpi-pipeline"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--region", default="asia-northeast3")
    ap.add_argument("--service", default="agent360")
    ap.add_argument("--common", default="common")
    ap.add_argument("--module", default="agent360")
    ap.add_argument("--domain", default="ubase.co.kr")
    ap.add_argument("--member")
    ap.add_argument("--file", help="grant: 명단 파일 (한 줄에 이메일 하나)")
    ap.add_argument("--role", help="grant: 앱 역할 admin|manager|sv|viewer 도 같이 등록")
    ap.add_argument("--teams", help="grant: sv/viewer 가 볼 팀 (쉼표 구분)")
    ap.add_argument("--agent-project", default="v11-2026", help="기존 데이터 에이전트가 있는 프로젝트")
    ap.add_argument("--agent-id", default="agent_f682354b-7695-4008-b37e-9d4cff706829",
                    help="데이터 에이전트 ID (AI BA CHAT (Volume)). 빈 값이면 AI 끔")
    ap.add_argument("--agent-datasets", default="Dynamic", help="에이전트가 읽는 데이터셋 (쉼표 구분)")
    ap.add_argument("--kpi-days", type=int, default=120, help="kpi-pipeline: 매일 다시 넣을 최근 일수")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run = Runner(a.dry_run)
    {"setup": cmd_setup, "deploy": cmd_deploy, "grant": cmd_grant, "url": cmd_url,
     "ai-access": cmd_ai_access, "kpi-pipeline": cmd_kpi_pipeline}[a.cmd](run, a)


if __name__ == "__main__":
    main()
