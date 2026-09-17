# WhatsApp Number Generator

Générateur de numéros de téléphone réalistes avec vérification WhatsApp et campagnes d'envoi de messages.

## Fonctionnalités

- **Génération** de numéros réalistes dans 28 pays (préfixes mobiles, villes, indicatifs)
- **Vérification WhatsApp** : via bridge Baileys (`wa_bridge/`) ou simulation de démo
- **Campagnes** : génération → test → envoi de masse avec délais anti-ban
- **Modèles de messages** : variables `{pays}`, `{ville}`, `{numero}`, `{nom}`
- **Liste noire** et détection de doublons
- **Score de qualité** par numéro, **tags** d'organisation
- **File de messages** avec retries (max 3)
- **Campagnes planifiées** et logs d'activité complets
- **Statistiques** : top villes, présence WhatsApp par pays, tableau de bord

## Architecture

- Backend : **FastAPI** (Python) — `main.py`
- Frontend : Jinja2 + Tailwind + Chart.js — `templates/index.html`
- Base de données : **Neon (PostgreSQL serverless)** — aucune donnée locale
- Bridge WhatsApp : **Node.js/Baileys** — `wa_bridge/server.js`

## Installation

```bash
pip install -r requirements.txt
node wa_bridge/install.sh          # ou: cd wa_bridge && npm install
```

## Configuration

La connexion à la base Neon est lue depuis `.env.local` (généré par le CLI Neon) :

```bash
npm i -g neon@latest && neon login
neon link --project-id <VOTRE_PROJET> --branch production -y
```

Variables optionnelles :

- `WHATSAPP_BRIDGE_URL` (défaut : `http://127.0.0.1:8755`)
- `SIMULATE_WHATSAPP=1` pour la démo sans bridge connecté

## Lancement

```bash
node wa_bridge/server.js    # 1. bridge WhatsApp (QR à scanner)
python main.py              # 2. application web sur http://localhost:8000
```

Ou via les scripts : `start_bridge.bat` puis `server_start.bat`.

## Tests

```bash
python e2e_test.py          # suite e2e (port 8071)
```

## Note légale

Cet outil est destiné à des usages respectant les conditions d'utilisation de WhatsApp et les réglementations locales (RGPD, opt-out). La liste noire et la détection de doublons existent pour éviter la sollicitation répétée de contacts.