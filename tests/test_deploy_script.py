"""배포 스크립트가 만드는 명령 확인 (실제 실행 없이 --dry-run)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "deploy.py"), *args, "--project", "v12-2027", "--dry-run"],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_deploy_is_private_with_iap_and_prod_env():
    code, out = _run("deploy")
    assert code == 0, out
    assert "--no-allow-unauthenticated" in out and "--iap" in out
    assert "ENV=prod" in out and "DATA_BACKEND=bigquery" in out and "ALLOWED_DOMAINS=ubase.co.kr" in out
    assert "gcp-sa-iap.iam.gserviceaccount.com" in out and "roles/run.invoker" in out
    assert "--allow-unauthenticated " not in out


def test_setup_grants_least_privilege():
    code, out = _run("setup")
    assert code == 0, out
    assert "roles/bigquery.jobUser" in out
    assert "roles/bigquery.dataViewer` ON SCHEMA `v12-2027.common`" in out
    assert "roles/bigquery.dataEditor` ON SCHEMA `v12-2027.agent360`" in out
    assert "roles/bigquery.admin" not in out


def test_grant_only_company_domain():
    code, out = _run("grant", "--member", "user:a@gmail.com")
    assert code != 0 and "ubase.co.kr" in out
    code, out = _run("grant", "--member", "group:agent360-users@ubase.co.kr")
    assert code == 0 and "roles/iap.httpsResourceAccessor" in out and "--resource-type=cloud-run" in out


def test_grant_from_file_registers_role(tmp_path):
    f = tmp_path / "m.txt"
    f.write_text("# 주석\nA.Kim@ubase.co.kr\n\nb.lee@ubase.co.kr  # 메모\na.kim@ubase.co.kr\n", encoding="utf-8")
    code, out = _run("grant", "--file", str(f), "--role", "manager")
    assert code == 0, out
    assert out.count("add-iam-policy-binding") == 2          # 중복·대소문자 정리
    assert "user:a.kim@ubase.co.kr" in out and "user_roles ← 2명 role=manager" in out
    code, out = _run("grant", "--file", str(f), "--role", "sv")
    assert code != 0 and "--teams" in out


def test_managers_list_is_valid():
    lines = [l.split("#")[0].strip() for l in (ROOT / "access" / "managers.txt").read_text(encoding="utf-8").splitlines()]
    emails = [l for l in lines if l]
    assert emails and all(e.endswith("@ubase.co.kr") and e.count("@") == 1 for e in emails)
    assert len(emails) == len(set(e.lower() for e in emails))


def test_ai_access_and_deploy_env():
    code, out = _run("ai-access")
    assert code == 0, out
    assert "add-iam-policy-binding v11-2026" in out and "roles/geminidataanalytics.dataAgentUser" in out
    assert "roles/bigquery.dataViewer` ON SCHEMA `v11-2026.Dynamic`" in out
    assert "roles/bigquery.admin" not in out and "roles/owner" not in out and "roles/editor" not in out
    code, out = _run("deploy")
    assert "AI_AGENT_PROJECT=v11-2026" in out and "AI_AGENT_ID=agent_" in out
