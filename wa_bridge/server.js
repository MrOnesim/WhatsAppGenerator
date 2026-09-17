const express = require('express');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
} = require('@whiskeysockets/baileys');
const pino = require('pino');

const PORT = process.env.BRIDGE_PORT || 8755;
const app = express();
app.use(express.json());

let sockRef = null;
let connected = false;
let currentQr = null;
let lastError = null;

async function startWhatsApp() {
  try {
    const { state, saveCreds } = await useMultiFileAuthState('auth');
    const { version } = await fetchLatestBaileysVersion();

    sockRef = makeWASocket({
      version,
      auth: state,
      logger: pino({ level: 'silent' }),
      printQRInTerminal: false,
    });

    sockRef.ev.on('creds.update', saveCreds);

    sockRef.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;
      if (qr) {
        currentQr = qr;
        connected = false;
      }
      if (connection === 'open') {
        currentQr = null;
        connected = true;
        lastError = null;
        console.log('[bridge] CONNECTED to WhatsApp');
      }
      if (connection === 'close') {
        connected = false;
        lastError = lastDisconnect?.error?.message || 'Connection closed';
        const shouldReconnect =
          lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
        if (shouldReconnect) {
          console.log('[bridge] Reconnecting...');
          startWhatsApp();
        } else if (lastDisconnect?.error?.output?.statusCode === DisconnectReason.loggedOut) {
          console.log('[bridge] Logged out. Delete the auth folder and restart to scan a new QR.');
        }
      }
    });
  } catch (e) {
    lastError = e.message;
    console.error('[bridge] Startup error:', e.message);
  }
}

app.get('/status', (req, res) => {
  res.json({ connected, hasQr: !!currentQr, error: lastError });
});

app.get('/qr', (req, res) => {
  res.json({ qr: currentQr });
});

app.post('/check', async (req, res) => {
  const phone = String(req.body.phone || '').replace(/\D/g, '');
  if (!phone) return res.status(400).json({ error: 'missing phone' });
  if (!connected || !sockRef) return res.status(409).json({ error: 'NOT_CONNECTED' });
  try {
    const results = await sockRef.onWhatsApp(phone);
    const found = results && results.length > 0 ? results[0] : null;
    res.json({ exists: !!(found && found.exists), wa_id: found ? found.jid : null });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/send', async (req, res) => {
  const phone = String(req.body.phone || '').replace(/\D/g, '');
  const text = String(req.body.message || '');
  if (!phone || !text) return res.status(400).json({ error: 'missing phone or message' });
  if (!connected || !sockRef) return res.status(409).json({ error: 'NOT_CONNECTED' });
  try {
    const jid = phone + '@s.whatsapp.net';
    const sent = await sockRef.sendMessage(jid, { text });
    res.json({ sent: !!sent, id: sent?.key?.id });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => console.log('[bridge] HTTP bridge listening on port ' + PORT));
startWhatsApp();