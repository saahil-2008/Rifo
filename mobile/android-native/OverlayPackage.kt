package com.rifo.overlay

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.uimanager.ViewManager

/**
 * Registers the Rifo overlay native module. Classic (non-TurboModule) package:
 * the host app must run with newArchEnabled=false (see PATCHES.md). Add this
 * package to MainApplication.getPackages().
 */
class OverlayPackage : ReactPackage {

    override fun createNativeModules(reactContext: ReactApplicationContext): List<NativeModule> =
        listOf(OverlayModule(reactContext))

    override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<*, *>> =
        emptyList()
}
