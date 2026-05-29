#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Build the Expo Web bundle for production hosting on
# Cloudflare Pages / Vercel / Netlify / S3 / GitHub Pages.
#
# What this does:
#   1. Cleans the previous build
#   2. Exports the Expo web bundle as static files into ./dist/
#   3. Bakes the production backend URL into the JS bundle
#
# After running:  upload the contents of  ./dist/  to your host.
# ─────────────────────────────────────────────────────────
set -e

# ─── Configure these once ───────────────────────────────
BACKEND_URL="${BACKEND_URL:-https://network-pay-1.emergent.host}"
OUTDIR="${OUTDIR:-./dist}"
# ────────────────────────────────────────────────────────

echo "🧹  Cleaning previous build at $OUTDIR…"
rm -rf "$OUTDIR"

echo "🛠   Building Expo web bundle (this can take 1-3 min)…"
echo "    Backend URL → $BACKEND_URL"
echo

EXPO_PUBLIC_BACKEND_URL="$BACKEND_URL" \
  npx expo export --platform web --output-dir "$OUTDIR"

echo
echo "✅  Build complete!"
echo "    Output: $OUTDIR/"
echo "    Size:   $(du -sh "$OUTDIR" | cut -f1)"
echo
echo "📤  Next steps:"
echo "    • Cloudflare Pages → upload the contents of $OUTDIR/"
echo "    • Vercel          → drag-and-drop $OUTDIR/ to vercel.com/new"
echo "    • Netlify         → drag-and-drop $OUTDIR/ to app.netlify.com/drop"
