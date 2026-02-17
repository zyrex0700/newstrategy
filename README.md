# MT5 XAUUSD Scalping Bot (VWAP + EMA + ATR)

این ربات پایتونی مستقیم به متاتریدر 5 وصل می‌شود، دیتا را از همان MT5 می‌گیرد، و بر اساس نسخه‌ی مکانیکی استراتژی شما برای XAUUSD پوزیشن می‌گیرد.

## چرا فقط `Bot started...` می‌بینی؟
این یعنی ربات اجرا شده، ولی یکی از فیلترها اجازه‌ی ورود نداده است. در نسخه جدید، هر چند ثانیه دلیل انتظار را چاپ می‌کند:
- `out_of_session` → خارج از ساعت مجاز
- `spread_too_wide` → اسپرد زیاد
- `no_5m_bias` → بایاس 5 دقیقه شکل نگرفته
- `no_1m_entry` → ستاپ ورود 1 دقیقه هنوز کامل نیست
- `existing_position_for_magic` → پوزیشن باز قبلی دارید

## مهم
- این کد برای آموزش/تست است و سود تضمین نمی‌کند.
- قبل از حساب واقعی، روی دمو و با لاگ کامل تست کنید.
- در Python API متاتریدر، دسترسی مستقیم به بافر اندیکاتور سفارشی MT5 (مثل VWAP که داخل Free Indicators نصب کرده‌اید) ساده/مستقیم نیست. در این کد VWAP داخل پایتون از دیتای کندل محاسبه می‌شود.

## نصب
```bash
pip install MetaTrader5 pandas numpy
```

## پیش‌نیاز MT5
1. MT5 باز باشد و لاگین کرده باشید.
2. AutoTrading در MT5 روشن باشد.
3. در حساب بروکر، اجازه معامله الگوریتمی فعال باشد.
4. نماد `XAUUSD` در Market Watch فعال باشد.

## اجرا
فایل `mt5_xau_scalper.py` را باز کنید و این بخش را پر کنید:
```python
cfg = BotConfig(
    login=12345678,
    password="YOUR_PASSWORD",
    server="YOUR_BROKER_SERVER",
)
```

سپس:
```bash
python mt5_xau_scalper.py
```

## اگر می‌خواهی خارج از سشن هم کار کند
پیش‌فرض ربات فقط 13 تا 17 UTC فعال است. اگر می‌خواهی همیشه چک کند:
```python
cfg = BotConfig(
    login=12345678,
    password="YOUR_PASSWORD",
    server="YOUR_BROKER_SERVER",
    enable_session_filter=False,
)
```

## منطق اصلی
- بایاس 5 دقیقه: VWAP + EMA(20/50/200)
- تریگر 1 دقیقه: پولبک نزدیک VWAP + RSI + شرط کندلی ساده
- حدضرر: بیشینه‌ی Swing یا 1.2×ATR
- حدسود: 1.5R
- مدیریت ریسک: درصد ثابت از بالانس
- فیلتر زمان: پیش‌فرض 13 تا 17 UTC
- فیلتر اسپرد: پیش‌فرض حداکثر 0.25 دلار

## شخصی‌سازی سریع
پارامترها داخل `BotConfig`:
- `risk_per_trade`
- `max_spread_usd`
- `enable_session_filter`
- `session_start_utc`, `session_end_utc`
- `status_log_seconds`
- `ema_*`, `rsi_period`, `atr_period`
- `magic`

## پیشنهاد حرفه‌ای
اگر می‌خواهید دقیقا از اندیکاتور VWAP نصب‌شده‌ی MT5 استفاده شود (نه VWAP محاسبه‌شده در پایتون)، بهترین راه:
- یک اکسپرت/اسکریپت MQL5 بسازیم که با `iCustom` بافر VWAP را بخواند.
- یا یک پل MQL5↔Python طراحی کنیم تا مقدار بافر به پایتون ارسال شود.
