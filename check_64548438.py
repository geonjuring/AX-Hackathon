"""리포트(05_수시4_LOT이상분석_64548438.pdf) 숫자와 비교 — 모두 ✓ 이면 계산 엔진 OK"""
import lot_analysis as LA

r = LA.analyze("64548438")
print("비교 LOT:", r["비교"], "(리포트: 64477125, 64455797)")
pt, bt, j = r["공정조건"], r["배럴"], r["판정표"]
L, C1, C2 = "64548438", "64477125", "64455797"
def get(df, key, col, keycol="항목"):
    try: return float(df.loc[df[keycol] == key, col].iloc[0])
    except Exception: return None
checks = [
    ("메인모터 RPM 가운데값", get(pt, "메인모터 RPM", f"{L} 가운데값"), 538.0),
    ("비교1 메인모터 RPM", get(pt, "메인모터 RPM", f"{C1} 가운데값"), 638.0),
    ("비교2 메인모터 RPM", get(pt, "메인모터 RPM", f"{C2} 가운데값"), 589.0),
    ("진공 가운데값", get(pt, "진공", f"{L} 가운데값"), -650.0),
    ("전류 가운데값", get(pt, "전류", f"{L} 가운데값"), 416.0),
    ("4존 초과%", get(bt, "4존", f"{L} 초과%", "배럴"), 96.6),
    ("4존 초과건", get(bt, "4존", f"{L} 초과건", "배럴"), 1193),
    ("4존 실측", get(bt, "4존", f"{L} 실측", "배럴"), 227.0),
]
for n, a, e in checks:
    ok = a is not None and abs(a - e) < 0.05 + abs(e) * 0.001
    print(f"{'✓' if ok else '✗'} {n}: 앱 {a} / 리포트 {e}")
i = r["info"]
print(f"{'✓' if int(i.get('n_run', 0)) == 1235 and int(i.get('n_all', 0)) == 1452 else '✗'} 가동/전체 기록: {i.get('n_run')}/{i.get('n_all')} (리포트 1235/1452)")
print(f"{'✓' if abs(i.get('생산량', 0) - 16093) < 1 else '✗'} 생산량: {i.get('생산량')} (리포트 16093)")
print("\n판정표"); print(j.to_string(index=False))
