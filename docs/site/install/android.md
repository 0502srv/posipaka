# Android / Termux

Posipaka працює на Android через Termux.

## Встановлення Termux

1. Встановіть [Termux](https://f-droid.org/en/packages/com.termux/) з F-Droid
2. Встановіть [Termux:API](https://f-droid.org/en/packages/com.termux.api/)

## Встановлення Posipaka

```bash
pkg update && pkg upgrade
pkg install python git
pip install posipaka
posipaka setup --platform android
```

## Автозапуск

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-posipaka.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
posipaka start
EOF
chmod +x ~/.termux/boot/start-posipaka.sh
```

## Особливості на Android

- **Battery Manager**: автоматичне зниження навантаження при низькому заряді
- **Termux API**: сповіщення, TTS, геолокація
- **Resource Profile**: автоматично обирається `minimal` для пристроїв з <2GB RAM

## Рекомендовані пристрої

- RAM: 4GB+ (мінімум 2GB)
- Сховище: 2GB+ вільного місця
- Android: 8.0+
