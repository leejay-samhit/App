# ProGuard / R8 keep rules used by the Slangcart Android release build
#
# These rules are passed to R8 through `expo-build-properties`
# (`app.json` → plugins → expo-build-properties → android.extraProguardRules).
# The file itself is documentation + the single place to review them: the
# string in app.json is generated from this list, line for line.
#
# WHY SO MANY KEEPS?
# React Native, Expo and Hermes resolve native modules, view managers and
# TurboModule specs BY NAME at runtime. R8 cannot see those references, so
# anything it renames or removes disappears silently at runtime — a white
# screen, or worse, a payment sheet that never opens. Everything below is a
# runtime-reflection surface in this app. Nothing here is "just in case".

# ── React Native / Hermes core ───────────────────────────────────────────
-keep class com.facebook.react.** { *; }
-keep class com.facebook.hermes.** { *; }
-keep class com.facebook.jni.** { *; }
-keep class com.facebook.fbreact.specs.** { *; }
-keep class com.facebook.proguard.annotations.DoNotStrip
-keep @com.facebook.proguard.annotations.DoNotStrip class * { *; }
-keepclassmembers class * { @com.facebook.proguard.annotations.DoNotStrip *; }
-keepclassmembers class * { @com.facebook.react.bridge.ReactMethod *; }
-keepclassmembers class * { @com.facebook.react.uimanager.annotations.ReactProp *; }
-keepclassmembers class * { @com.facebook.react.uimanager.annotations.ReactPropGroup *; }
-keep,includedescriptorclasses class * extends com.facebook.react.bridge.NativeModule { *; }
-keep,includedescriptorclasses class * extends com.facebook.react.uimanager.ViewManager { *; }
-keep,includedescriptorclasses class * extends com.facebook.react.bridge.BaseJavaModule { *; }
-keepclassmembers,includedescriptorclasses class * extends com.facebook.react.bridge.JavaScriptModule { *; }
-dontwarn com.facebook.react.**

# ── Expo modules (resolved by package name at startup) ────────────────────
-keep class expo.modules.** { *; }
-keep class versioned.host.exp.exponent.modules.** { *; }
-keep class host.exp.exponent.** { *; }
-keep @expo.modules.core.interfaces.DoNotStrip class * { *; }
-keepclassmembers class * { @expo.modules.core.interfaces.ExpoProp *; }
-keepclassmembers class * { @expo.modules.core.interfaces.ExpoMethod *; }
-dontwarn expo.modules.**

# ── Reanimated / Worklets / Gesture Handler / Screens / SVG / WebView ─────
-keep class com.swmansion.reanimated.** { *; }
-keep class com.swmansion.worklets.** { *; }
-keep class com.swmansion.gesturehandler.** { *; }
-keep class com.swmansion.rnscreens.** { *; }
-keep class com.horcrux.svg.** { *; }
-keep class com.reactnativecommunity.webview.** { *; }
-dontwarn com.swmansion.**

# ── WebView bridge — Razorpay checkout runs inside a WebView ──────────────
# A renamed @JavascriptInterface method breaks the payment callback with no
# error anywhere. Payments are the last thing that may be optimised away.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class * extends android.webkit.WebViewClient { *; }
-keep class * extends android.webkit.WebChromeClient { *; }
# Razorpay native SDK (kept in case the native checkout is ever added)
-keep class com.razorpay.** { *; }
-dontwarn com.razorpay.**
-optimizations !method/inlining/*

# ── Firebase / Google Play services — push notifications ──────────────────
-keep class com.google.firebase.** { *; }
-keep class com.google.android.gms.** { *; }
-keep class com.google.android.play.core.** { *; }
-keep class * extends com.google.firebase.messaging.FirebaseMessagingService { *; }
-keepnames class com.google.firebase.provider.FirebaseInitProvider
-dontwarn com.google.firebase.**
-dontwarn com.google.android.gms.**
-dontwarn com.google.android.play.core.**

# ── Device features used through reflection-heavy Expo modules ────────────
-keep class androidx.biometric.** { *; }          # expo-local-authentication
-keep class androidx.security.crypto.** { *; }    # expo-secure-store
-keep class androidx.camera.** { *; }             # expo-camera
-keep class androidx.exifinterface.** { *; }      # expo-image-manipulator
-dontwarn androidx.**

# ── Networking (OkHttp / Okio ship their own rules but warn loudly) ───────
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**
-keepclassmembers class * implements okhttp3.Interceptor { *; }

# ── Kotlin / AndroidX plumbing R8 needs to keep intact ────────────────────
-keep class kotlin.Metadata { *; }
-keepclassmembers class **$WhenMappings { <fields>; }
-keepclassmembers class kotlin.Metadata { public <methods>; }
-keep class kotlinx.coroutines.android.AndroidDispatcherFactory { *; }
-dontwarn kotlinx.coroutines.**
-keep class * implements android.os.Parcelable { public static final ** CREATOR; }
-keepclassmembers enum * { public static **[] values(); public static ** valueOf(java.lang.String); }
-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod,Exceptions

# ── Crash reports must stay readable ─────────────────────────────────────
# Line numbers are kept and the source file name is masked, so stack traces
# still map through mapping.txt after Play Console de-obfuscation.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
