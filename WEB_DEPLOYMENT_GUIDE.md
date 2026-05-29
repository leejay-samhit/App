# 🚀 Deploying `networkrupay` to a Custom Domain

This app is built on **Expo (mobile-first)**, but Expo also compiles to a fully-static web bundle. We exported that bundle to `frontend/dist/` so you can host it ANYWHERE with custom-domain support — Cloudflare Pages, Vercel, Netlify, S3, etc.

**Backend stays on Emergent** at `https://network-pay-1.emergent.host` — no change there.

---

## ✅ Already Done For You

| Task | Status |
|---|---|
| `frontend/dist/` static web build (24 MB) | ✅ Ready |
| Backend URL baked into bundle | ✅ `https://network-pay-1.emergent.host` |
| Backend CORS allow-list includes `www.networkrupay.com` | ✅ |
| Helper script `frontend/build-web.sh` for future rebuilds | ✅ |
| `_redirects` rule for SPA deep-linking | ✅ (auto-generated below) |

---

## 🟢 Option 1 — Cloudflare Pages (RECOMMENDED — Free, Fast, Easiest)

### Why Cloudflare Pages
- ✅ **Unlimited** bandwidth, free
- ✅ Custom domain via CNAME (you already have GoDaddy DNS configured!)
- ✅ Automatic SSL (Let's Encrypt)
- ✅ Global CDN
- ✅ 500 builds/month free

### Step-by-Step

#### 1. Download `dist/` to Your Laptop

Since the build sits inside this Emergent container, you need to download it first:
```bash
# Option A: ZIP it inside the chat container
cd /app/frontend && zip -r /tmp/dist.zip dist/
# Then download /tmp/dist.zip via Emergent's file browser
```

Or alternatively, push your code to GitHub and let Cloudflare build it (see Option 1b below).

#### 2. Sign Up at Cloudflare Pages
- Go to **https://pages.cloudflare.com**
- Sign up (free, no credit card)
- Click **Create a project**

#### 3. Upload Direct (Drag-and-Drop)
- Click **Upload assets**
- Project name: `networkrupay`
- Drag the contents of `dist/` (NOT the dist folder itself — the files INSIDE it) into the uploader
- Click **Deploy**
- Wait ~30 seconds → you get a temp URL like `networkrupay.pages.dev`

#### 4. Add Custom Domain
- Inside the Cloudflare Pages project → **Custom domains** tab
- Click **Set up a custom domain**
- Enter: `www.networkrupay.com` → Click **Continue**
- Cloudflare auto-detects your existing CNAME and links it instantly
- SSL auto-issues in 2–5 min

#### 5. Update GoDaddy DNS
Change your existing CNAME to point at Cloudflare Pages instead of Emergent:

```
Type:   CNAME
Name:   www
Value:  networkrupay.pages.dev      ← NEW target
TTL:    1 hour
```

Replace the previous CNAME (`network-pay-1.emergent.host`) with this new one.

✅ Done. Visit `https://www.networkrupay.com` after DNS re-propagates (5-30 min).

---

### Option 1b — Cloudflare Pages via GitHub (Auto-Deploy on Push)

If you'd rather not zip-and-upload manually each time, connect a GitHub repo:

1. Push `/app` to a GitHub repo (private is fine)
2. In Cloudflare Pages → **Create a project** → **Connect to Git**
3. Select your repo
4. Build settings:
   - **Build command:** `cd frontend && bash build-web.sh`
   - **Build output directory:** `frontend/dist`
   - **Environment variable:** `BACKEND_URL=https://network-pay-1.emergent.host`
5. Click **Deploy**
6. Every `git push` auto-deploys

---

## 🟡 Option 2 — Vercel (Also Free, Also Excellent)

### Step-by-Step

#### 1. Sign up at **https://vercel.com/signup**

#### 2. Drag-and-Drop Deploy
- Visit `https://vercel.com/new`
- Click **Drag and drop your project here**
- Drop your local `dist/` folder
- Wait ~30 sec → temp URL ready

#### 3. Add Custom Domain
- Inside your Vercel project → **Settings** → **Domains**
- Enter `www.networkrupay.com` → **Add**
- Vercel shows you the CNAME value to use

#### 4. Update GoDaddy DNS
```
Type:   CNAME
Name:   www
Value:  cname.vercel-dns.com         ← Vercel's standard CNAME
TTL:    1 hour
```

---

## 🔵 Option 3 — Netlify Drop (Easiest of All)

For non-technical users — literally drag-and-drop:

1. Go to **https://app.netlify.com/drop**
2. Drag your `dist/` folder into the page
3. Get an instant URL
4. Click **Site settings → Domain management → Add custom domain**
5. Enter `www.networkrupay.com`
6. Update GoDaddy DNS as shown by Netlify

---

## 🔁 To Rebuild After Code Changes

Run inside the Emergent container (or anywhere with the code):

```bash
cd /app/frontend
bash build-web.sh
```

This regenerates `dist/`. Re-upload that folder to your chosen host (Cloudflare/Vercel/Netlify). If using Git-connected deploys, just `git push` and the host rebuilds automatically.

---

## 🔧 Custom Backend URL

If you ever change your backend (e.g., move to your own server), just edit the URL in the build command:

```bash
BACKEND_URL=https://api.yourdomain.com bash build-web.sh
```

The URL gets baked into the new bundle automatically.

---

## 🛡️ Things to Verify After Going Live

After your custom domain is up:

1. ✅ **Open `https://www.networkrupay.com`** → should load your app
2. ✅ **Login** with `admin@app.com / Admin@123` → should work (CORS pre-configured)
3. ✅ **Check browser DevTools → Network** → API calls should go to `network-pay-1.emergent.host/api/*` and return 200
4. ✅ **Check Console** → no CORS errors

If you see CORS errors, the backend hasn't been re-deployed with the new CORS allow-list. Click **Re-deploy changes** in your Emergent Manage Deployments modal.

---

## 🆘 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 404 on deep links (e.g. `/admin`) | Host not configured for SPA | Cloudflare/Vercel auto-handle this; Netlify needs `_redirects` file (auto-included) |
| "CORS error" in browser console | Backend not re-deployed with new CORS | Click "Re-deploy changes" in Emergent |
| Blank white page | Backend URL wrong in build | Re-run `build-web.sh` with correct `BACKEND_URL` |
| SSL error after domain link | Wait 5-15 min for cert provisioning | Be patient :) |
| DNS not resolving | Old GoDaddy CNAME cached | Wait up to 1 hour, or flush DNS with `ipconfig /flushdns` (Win) / `sudo dscacheutil -flushcache` (Mac) |

---

## 📞 If You Hit Issues

Reply here with:
- Which host you chose (Cloudflare / Vercel / Netlify)
- The error message you see
- A screenshot

I'll diagnose and fix.
