@echo off
REM WhatsApp Bridge (Baileys) - verification reelle et envoi de messages
cd /d "%~dp0wa_bridge"
if not exist node_modules (
    echo Installation des dependances npm...
    call npm install --no-fund --no-audit
)
echo Demarrage du bridge WhatsApp (port 8755)...
echo 1. Scannez le QR code affiche avec votre telephone (WhatsApp > Appareils connectes)
echo 2. Le bridge est connecte quand "CONNECTED to WhatsApp" apparait
node server.js