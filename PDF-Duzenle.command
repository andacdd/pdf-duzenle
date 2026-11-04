#!/bin/bash
# Mac: çift tıkla. İlk açılışta gerekli parçaları indirir (1-2 dk).
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Bu uygulama 'uv' adlı küçük bir araçla çalışır ve bu bilgisayarda yok."
  read -r -p "Şimdi kurulsun mu? (e/h) " c
  if [ "$c" = "e" ] || [ "$c" = "E" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "Kurulmadı. Çıkılıyor."; read -r -p "Kapatmak için Enter."; exit 1
  fi
fi
uv run --no-dev server.py "$@"
