/**
 * Injects the Truecaller Client ID into the merged AndroidManifest.
 *
 * The SDK reads it from `<application><meta-data
 * android:name="com.truecaller.android.sdk.ClientId" .../>` — it is NOT a
 * TcSdkOptions.Builder argument. An Android OAuth client ID is necessarily
 * shipped inside the APK, so it is an identifier rather than a secret; the
 * backend still verifies every code against Truecaller's own servers.
 *
 * The value is read from the environment at prebuild time so it never sits in
 * source control. If it is missing the plugin does NOT fail the build: the
 * app simply reports one-tap verification as unavailable and falls back to
 * manual number entry.
 */
const { withAndroidManifest, AndroidConfig } = require("expo/config-plugins");

const META_KEY = "com.truecaller.android.sdk.ClientId";

const withTruecaller = (config) => {
  const clientId = (
    process.env.EXPO_PUBLIC_TRUECALLER_CLIENT_ID ||
    process.env.TRUECALLER_CLIENT_ID ||
    ""
  ).trim();

  if (!clientId) {
    console.warn(
      "[withTruecaller] EXPO_PUBLIC_TRUECALLER_CLIENT_ID is not set — " +
        "one-tap verification will be unavailable in this build.",
    );
    return config;
  }

  return withAndroidManifest(config, (cfg) => {
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(cfg.modResults);
    AndroidConfig.Manifest.addMetaDataItemToMainApplication(app, META_KEY, clientId);
    return cfg;
  });
};

module.exports = withTruecaller;
