"""팀 구성(OPS TL) 샘플 — 가짜 이름·사번 (실제 개인정보 없음).

python sample_data/roster/generate.py → agent_info.json, board.json
agent_info = Standard INFO TABLE 형식(일부 열), board = 지금 OPS TL 보드(행 형식).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
random.seed(7)
SUR = list("김이박최정강조윤장임한오서신권황안송류홍")
GIV = ["하나", "두리", "세아", "도윤", "서연", "지우", "민준", "하린", "예준", "수아", "지호", "유나", "시우", "다은", "준서",
       "채원", "현우", "소율", "건우", "나연", "은호", "가윤", "태민", "라희", "우진", "보민", "선우", "이안", "로아", "주원"]
ROMA = {"김": "Kim", "이": "Lee", "박": "Park", "최": "Choi", "정": "Jung", "강": "Kang", "조": "Cho", "윤": "Yun", "장": "Jang",
        "임": "Lim", "한": "Han", "오": "Oh", "서": "Seo", "신": "Shin", "권": "Kwon", "황": "Hwang", "안": "Ahn", "송": "Song",
        "류": "Ryu", "홍": "Hong"}
NICK = ["Aria", "Ben", "Cora", "Dean", "Ella", "Finn", "Gia", "Hugo", "Iris", "Jude", "Kai", "Luna", "Milo", "Nora", "Owen",
        "본명"]
TLS = ["TL 가람", "TL 나래", "TL 다솜", "TL 라온"]


def main():
    info, board, used = [], [], set()
    for i in range(44):
        while True:
            s, g = random.choice(SUR), random.choice(GIV)
            if s + g not in used:
                used.add(s + g)
                break
        emp = f"9{random.randint(5, 6)}{i:06d}"
        joined = f"202{random.randint(3, 6)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        left = "2026-11-15" if i in (40, 41) else ""
        info.append({"emp_id": emp, "airbnb_id": str(30000000 + i), "name": s + g, "e_name": f"{g} {ROMA[s]}",
                     "ldap": f"ub_sample_{i:03d}", "joined": joined, "role": "CSR", "market": "KR", "left": left})
        if i < 40 or i == 40:   # 40번은 퇴사했는데 아직 보드에 남아 있음 (경고 예시)
            board.append({"tl": TLS[i % 4], "shift": "US" if i % 3 else "EU", "emp_id": emp, "name": s + g,
                          "e_name": info[-1]["e_name"], "display_name": random.choice(NICK), "date": "", "note": ""})
    board.append({"tl": TLS[0], "shift": "US", "emp_id": "", "name": "트레이닝1", "e_name": "", "display_name": "",
                  "date": "", "note": "사번 발급 전"})
    (HERE / "agent_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "board.json").write_text(json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    print("만듦:", len(info), len(board))


if __name__ == "__main__":
    main()
