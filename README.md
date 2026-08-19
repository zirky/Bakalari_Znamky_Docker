# Balalari_Znamky_Docker

Docker webová aplikace pro jednoho studenta: známky z Bakalářů, kladné i záporné odměny a Lightning výplaty přes LNURL/pay nebo invoice.

## Stav projektu

Základní skeleton obsahuje FastAPI backend, Vue frontend, SQLite a Docker Compose. Tajné údaje patří pouze do lokálního `.env` nebo Docker secrets. Do repozitáře se nikdy neukládají skutečné přihlašovací údaje, API klíče ani PINy.

## Porty

- Frontend: http://localhost:5273
- Backend: http://localhost:8080
- Healthcheck: http://localhost:8080/api/health

## Spuštění

```bash
cp .env.example .env
docker compose up --build
```

SQLite databáze je uložena v `./data/app.db`.

## Plánované části

- rodičovský PIN s automatickým odhlášením po 30 sekundách nečinnosti,
- dětský read-only panel bez PINu,
- integrace veřejného API Bakalářů,
- pravidla kladných i záporných odměn,
- backtest od nastavitelného data,
- CoinGecko kurz CZK/BTC,
- LNURL/pay a klasický invoice,
- ruční nebo automatické výplaty,
- statistiky podle předmětů a období.
