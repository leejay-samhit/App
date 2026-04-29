module.exports = function (api) {
  api.cache(true);
  const isProd = process.env.NODE_ENV === "production" || process.env.BABEL_ENV === "production";
  return {
    presets: ["babel-preset-expo"],
    plugins: isProd
      ? [
          // Strip console.* in production builds (keeps console.warn + console.error for crashlytics).
          ["transform-remove-console", { exclude: ["error", "warn"] }],
        ]
      : [],
  };
};
