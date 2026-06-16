from binacci.sentinel import Sentinel

def test_depeg_and_flash_and_broad():
    s = Sentinel()
    # seed prices
    s.check({"USDT": 1.0, "BNB": 600.0, "ETH": 3000.0})
    # de-peg -> critical
    ev = s.check({"USDT": 0.90, "BNB": 600.0, "ETH": 3000.0})
    assert ev["critical"] and ev["depeg"]
    # single flash move is logged but not critical on its own
    s2 = Sentinel(); s2.check({"BNB": 600.0})
    ev2 = s2.check({"BNB": 700.0})  # +16.7%
    assert any(a["type"] == "flash_move" for a in ev2["new_alerts"]) and not ev2["critical"]
    # broad crash -> critical
    s3 = Sentinel()
    base = {f"A{i}": 100.0 for i in range(10)}
    s3.check(base)
    crash = {k: 80.0 for k in base}  # all -20%
    ev3 = s3.check(crash)
    assert ev3["broad_crash"] and ev3["critical"]

def test_status():
    s = Sentinel(); st = s.status()
    assert st["armed"] and "thresholds" in st and "USDT" in st["stables_watched"]
