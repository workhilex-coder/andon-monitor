Andon Monitor – opravené soubory

Co je hotové:
- opravené prohození H / TL ve scraperu
- web upravený tak, aby správně ukazoval typ alarmu
- přidané push notifikace přes Web Push
- funguje pro Android
- funguje i pro iPhone, ale na iOS musí být stránka přidaná na plochu a spuštěná jako web app

Nasazení:
1) Nahraj server.py a requirements.txt na PythonAnywhere
2) Spusť:
   pip install -r requirements.txt

3) Vygeneruj VAPID klíče:
   python generate_vapid.py

4) Do environmentu / WSGI configu dej:
   ANDON_SECRET=HiLex2024Andon
   VAPID_PUBLIC_KEY=...
   VAPID_PRIVATE_KEY=...
   VAPID_CLAIMS_SUB=mailto:tvuj@email.cz

5) Restartni web app na PythonAnywhere

6) Na PC ve výrobě nahraď scraper.py touto verzí

Poznámka k iPhonu:
- otevřít v Safari
- Sdílet → Přidat na plochu
- spustit z ikony na ploše
- potom kliknout na "Zapnout notifikace"
