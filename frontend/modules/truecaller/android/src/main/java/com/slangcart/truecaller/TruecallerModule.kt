package com.slangcart.truecaller

import android.content.Intent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.FragmentActivity
import com.truecaller.android.sdk.oAuth.TcOAuthCallback
import com.truecaller.android.sdk.oAuth.TcOAuthData
import com.truecaller.android.sdk.oAuth.TcOAuthError
import com.truecaller.android.sdk.oAuth.TcSdk
import com.truecaller.android.sdk.oAuth.TcSdkOptions
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * Truecaller OAuth SDK 3.3.0 — one-tap mobile number verification.
 *
 * The Client ID is NOT passed here: the SDK reads it from the merged
 * AndroidManifest meta-data `com.truecaller.android.sdk.ClientId`, which the
 * `withTruecaller` config plugin injects at build time.
 *
 * The OAuth `state` and the PKCE `code_challenge` are NOT generated here
 * either — Slangcart's backend mints them and keeps the matching verifier, so
 * this module cannot fabricate a successful verification. All this code does
 * is show Truecaller's consent sheet and hand the resulting one-time
 * authorization code back to JS, which posts it to the server for checking.
 */
class TruecallerModule : Module() {

  private var launcher: ActivityResultLauncher<Intent>? = null
  private var launcherActivity: FragmentActivity? = null
  private var inFlight = false
  private var sdkReady = false

  private val callback = object : TcOAuthCallback {
    override fun onSdkReady() {
      sdkReady = true
      sendEvent("onSdkReady", mapOf("ready" to true))
    }

    override fun onSuccess(tcOAuthData: TcOAuthData) {
      inFlight = false
      sendEvent(
        "onSuccess",
        mapOf(
          "authorizationCode" to tcOAuthData.authorizationCode,
          // JS compares this with the state the server issued; a mismatch is
          // treated as a failure and never sent on for exchange.
          "state" to tcOAuthData.state,
          "scopesGranted" to tcOAuthData.scopesGranted.toList(),
        ),
      )
    }

    override fun onFailure(tcOAuthError: TcOAuthError) {
      inFlight = false
      sendEvent(
        "onFailure",
        mapOf("code" to tcOAuthError.errorCode, "message" to (tcOAuthError.errorMessage ?: "")),
      )
    }

    override fun onVerificationRequired(tcOAuthError: TcOAuthError?) {
      // Only reachable with OPTION_VERIFY_ALL_USERS, which this app does not
      // request. Reported so JS can fall back to manual entry.
      inFlight = false
      sendEvent(
        "onVerificationRequired",
        mapOf("code" to (tcOAuthError?.errorCode ?: -1), "message" to (tcOAuthError?.errorMessage ?: "")),
      )
    }
  }

  override fun definition() = ModuleDefinition {
    Name("Truecaller")

    Events("onSdkReady", "onSuccess", "onFailure", "onVerificationRequired")

    AsyncFunction("isUsable") {
      val activity = appContext.currentActivity as? FragmentActivity ?: return@AsyncFunction false
      try {
        ensureInit(activity)
        // initAsync is asynchronous: querying the flow before onSdkReady can
        // report false on a phone that is perfectly capable, so wait briefly.
        var waited = 0L
        while (!sdkReady && waited < 2000L) {
          Thread.sleep(50)
          waited += 50
        }
        TcSdk.getInstance().isOAuthFlowUsable
      } catch (e: Exception) {
        false
      }
    }.runOnQueue(Queues.MAIN)

    /**
     * Shows Truecaller's consent sheet.
     *
     * @param state          server-issued, echoed back in onSuccess
     * @param codeChallenge  S256 challenge for the server-held verifier
     */
    AsyncFunction("requestVerification") { state: String, codeChallenge: String ->
      val activity = appContext.currentActivity as? FragmentActivity
        ?: throw IllegalStateException("no_activity")
      if (inFlight) throw IllegalStateException("already_in_progress")

      ensureInit(activity)
      var waited = 0L
      while (!sdkReady && waited < 3000L) {
        Thread.sleep(50)
        waited += 50
      }
      if (!TcSdk.getInstance().isOAuthFlowUsable) {
        throw IllegalStateException("oauth_unavailable")
      }

      TcSdk.getInstance().setOAuthState(state)
      TcSdk.getInstance().setOAuthScopes(arrayOf("openid", "profile", "phone"))
      TcSdk.getInstance().setCodeChallenge(codeChallenge)

      inFlight = true
      TcSdk.getInstance().getAuthorizationCode(activity, launcher!!)
      true
    }.runOnQueue(Queues.MAIN)

    OnDestroy {
      try {
        TcSdk.clear()
      } catch (e: Exception) {
        // Nothing to clear.
      }
      launcher = null
      launcherActivity = null
      sdkReady = false
    }
  }

  /**
   * Initialises the SDK and the activity-result launcher for the CURRENT
   * activity. Re-initialising for a different activity requires clear() first,
   * otherwise the SDK keeps a stale callback/context.
   */
  private fun ensureInit(activity: FragmentActivity) {
    if (launcherActivity !== activity) {
      try {
        TcSdk.clear()
      } catch (e: Exception) {
        // First run — nothing to clear.
      }
      sdkReady = false
      // registerForActivityResult() throws once the activity is STARTED, and
      // this module is always called from a running screen. The keyed
      // activityResultRegistry API is the supported way to register late.
      launcher = activity.activityResultRegistry.register(
        "slangcart_truecaller",
        ActivityResultContracts.StartActivityForResult(),
      ) { result ->
        TcSdk.getInstance().onActivityResultObtained(activity, result.resultCode, result.data)
      }
      launcherActivity = activity
      val options = TcSdkOptions.Builder(activity, callback)
        .sdkOptions(TcSdkOptions.OPTION_VERIFY_ONLY_TC_USERS)
        .build()
      TcSdk.initAsync(options)
    }
  }
}
