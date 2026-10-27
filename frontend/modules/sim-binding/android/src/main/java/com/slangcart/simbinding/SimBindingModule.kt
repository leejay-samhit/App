package com.slangcart.simbinding

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * Slangcart SIM-binding readiness (Android only).
 *
 * WHAT IT DOES
 *   Reports whether a usable SIM / eSIM subscription is present, how many
 *   slots are active, and the PUBLIC network codes (MCC/MNC) of the first
 *   active subscription, plus a change signal when subscriptions move.
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 *   • No IMEI / IMSI / ICCID / SIM serial / subscription-id is read or
 *     returned. Those need restricted permissions and are not needed to
 *     answer "is a SIM present?".
 *   • No phone number is read off the SIM — even where the OS would offer
 *     one it is unreliable and is not proof of ownership.
 *   • No SMS is read or sent. The app holds no SMS permission at all.
 *
 * WHAT IT PROVES
 *   Presence only. "A SIM is in this handset" is NOT "this number belongs to
 *   this account" — that decision is made by the server after an external
 *   verifier confirms the number.
 */
class SimBindingModule : Module() {

  private var listener: SubscriptionManager.OnSubscriptionsChangedListener? = null

  private val context: Context?
    get() = appContext.reactContext

  override fun definition() = ModuleDefinition {
    Name("SimBinding")

    Events("onSubscriptionsChanged")

    Function("isSupported") {
      val ctx = context ?: return@Function false
      ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_TELEPHONY)
    }

    Function("hasPermission") {
      val ctx = context ?: return@Function false
      ctx.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) ==
        PackageManager.PERMISSION_GRANTED
    }

    AsyncFunction("getSimStatus") {
      readStatus()
    }

    OnStartObserving {
      startObserving()
    }

    OnStopObserving {
      stopObserving()
    }

    OnDestroy {
      stopObserving()
    }
  }

  // ── Core read ──────────────────────────────────────────────────────────
  private fun readStatus(): Map<String, Any?> {
    val ctx = context ?: return result("SIM_STATE_UNKNOWN", detail = "no_context")

    if (!ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_TELEPHONY)) {
      return result("DEVICE_UNSUPPORTED", detail = "no_telephony_hardware")
    }

    val granted = ctx.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) ==
      PackageManager.PERMISSION_GRANTED

    val telephony = ctx.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
      ?: return result("SIM_STATE_UNKNOWN", detail = "no_telephony_service")

    // The coarse SIM state needs no permission at all, so an ABSENT SIM can
    // be reported honestly even when the user refused the permission.
    val simState = telephony.simState
    if (simState == TelephonyManager.SIM_STATE_ABSENT) {
      return result("SIM_ABSENT", permission = granted, detail = "sim_state_absent")
    }

    if (!granted) {
      // We know *something* is in the slot but cannot enumerate it.
      return result("PERMISSION_DENIED", permission = false, detail = "read_phone_state_denied")
    }

    return try {
      val sm = ctx.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as? SubscriptionManager
      val subs = sm?.activeSubscriptionInfoList
      if (subs.isNullOrEmpty()) {
        // Slot populated but no ACTIVE subscription: locked / not provisioned
        // / deactivated eSIM profile. Not the same as "no SIM".
        val state = when (simState) {
          TelephonyManager.SIM_STATE_READY -> "SIM_STATE_UNKNOWN"
          TelephonyManager.SIM_STATE_UNKNOWN -> "SIM_STATE_UNKNOWN"
          else -> "SIM_ABSENT"
        }
        return result(state, permission = true, detail = "no_active_subscription:$simState")
      }

      var hasEsim = false
      var roaming = false
      for (info in subs) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && info.isEmbedded) hasEsim = true
        if (sm.isNetworkRoaming(info.subscriptionId)) roaming = true
      }

      val first = subs[0]
      val mcc: String
      val mnc: String
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        mcc = first.mccString ?: ""
        mnc = first.mncString ?: ""
      } else {
        @Suppress("DEPRECATION")
        mcc = first.mcc.toString()
        @Suppress("DEPRECATION")
        mnc = first.mnc.toString()
      }

      result(
        state = "SIM_PRESENT",
        permission = true,
        slots = subs.size,
        esim = hasEsim,
        roaming = roaming,
        mcc = mcc,
        mnc = mnc,
        detail = "active_subscriptions:${subs.size}",
      )
    } catch (e: SecurityException) {
      // OEM builds can refuse enumeration even with the permission granted.
      result("PERMISSION_DENIED", permission = granted, detail = "security_exception")
    } catch (e: Exception) {
      result("SIM_STATE_UNKNOWN", permission = granted, detail = "read_failed")
    }
  }

  private fun result(
    state: String,
    permission: Boolean = false,
    slots: Int = 0,
    esim: Boolean = false,
    roaming: Boolean = false,
    mcc: String = "",
    mnc: String = "",
    detail: String = "",
  ): Map<String, Any?> = mapOf(
    "state" to state,
    "permissionGranted" to permission,
    "slotCount" to slots,
    "hasEsim" to esim,
    "isRoaming" to roaming,
    // Public network codes only — these identify a CARRIER, never a person.
    "mcc" to mcc,
    "mnc" to mnc,
    "apiLevel" to Build.VERSION.SDK_INT,
    "detail" to detail,
  )

  // ── Change observation ─────────────────────────────────────────────────
  private fun startObserving() {
    val ctx = context ?: return
    if (listener != null) return
    val sm = ctx.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as? SubscriptionManager
      ?: return
    val l = object : SubscriptionManager.OnSubscriptionsChangedListener() {
      override fun onSubscriptionsChanged() {
        // Fires on SIM insert/removal, eSIM profile switch and carrier
        // changes. The payload is the full fresh reading so JS can send one
        // re-verification straight away.
        try {
          sendEvent("onSubscriptionsChanged", readStatus())
        } catch (e: Exception) {
          // Never crash the app from a system callback.
        }
      }
    }
    listener = l
    try {
      sm.addOnSubscriptionsChangedListener(l)
    } catch (e: Exception) {
      listener = null
    }
  }

  private fun stopObserving() {
    val ctx = context ?: return
    val l = listener ?: return
    listener = null
    try {
      val sm = ctx.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as? SubscriptionManager
      sm?.removeOnSubscriptionsChangedListener(l)
    } catch (e: Exception) {
      // Nothing to do — the listener is already gone.
    }
  }
}
