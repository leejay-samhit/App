// Expo config plugin — Phase 3 Session B
// ----------------------------------------
// Wires SSL pinning into the EAS Android build pipeline.
//
//   1. Copies assets/network_security_config.xml into
//      android/app/src/main/res/xml/ at prebuild time.
//   2. Adds android:networkSecurityConfig="@xml/network_security_config"
//      to the <application> tag in AndroidManifest.xml.
//   3. Also asserts android:usesCleartextTraffic="false" — belt-and-braces
//      against accidental http:// calls slipping through.
//
// Activation: referenced from app.json's plugins array.
//   "plugins": [..., "./plugins/network-security-config"]
//
// Expo Go ignores config plugins entirely — they only execute during EAS
// prebuild (eas build, expo run:android). That's why this file's presence
// doesn't break the current Expo Go preview.

const fs = require("fs");
const path = require("path");
const { withAndroidManifest, withDangerousMod } = require("@expo/config-plugins");

const FILENAME = "network_security_config.xml";
const SOURCE_REL = `assets/${FILENAME}`;
const RES_REL = `android/app/src/main/res/xml/${FILENAME}`;

function copyConfigFile(config) {
  return withDangerousMod(config, [
    "android",
    async (cfg) => {
      const src = path.join(cfg.modRequest.projectRoot, SOURCE_REL);
      const dest = path.join(cfg.modRequest.platformProjectRoot, "app/src/main/res/xml", FILENAME);
      if (!fs.existsSync(src)) {
        // Surface clearly in the EAS build log so a missing file doesn't silently degrade security.
        throw new Error(`[network-security-config] expected ${src} to exist but it doesn't`);
      }
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.copyFileSync(src, dest);
      return cfg;
    },
  ]);
}

function patchManifest(config) {
  return withAndroidManifest(config, async (cfg) => {
    const app = cfg.modResults.manifest.application?.[0];
    if (!app) throw new Error("[network-security-config] <application> tag not found in AndroidManifest");
    app.$["android:networkSecurityConfig"] = "@xml/network_security_config";
    app.$["android:usesCleartextTraffic"] = "false";
    return cfg;
  });
}

module.exports = function withNetworkSecurityConfig(config) {
  config = copyConfigFile(config);
  config = patchManifest(config);
  return config;
};
