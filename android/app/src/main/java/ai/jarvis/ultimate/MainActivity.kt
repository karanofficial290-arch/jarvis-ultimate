package ai.jarvis.ultimate

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import ai.jarvis.ultimate.ui.JarvisTheme
import ai.jarvis.ultimate.ui.LoginScreen
import ai.jarvis.ultimate.ui.MainScreen
import ai.jarvis.ultimate.ui.MainViewModel
import ai.jarvis.ultimate.ui.Phase
import ai.jarvis.ultimate.ui.StartupScreen

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    private val micPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) vm.pushToTalk() else vm.toast = "Microphone permission was denied. You can still type to Jarvis."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            JarvisTheme {
                when (vm.phase) {
                    Phase.STARTUP -> StartupScreen(vm)
                    Phase.LOGIN -> LoginScreen(vm)
                    Phase.READY -> MainScreen(vm, requestMic = ::requestMic)
                }
            }
        }
    }

    /** The microphone is opened only on an explicit tap, after the runtime permission is granted. */
    private fun requestMic() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            vm.pushToTalk()
        } else {
            micPermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    // Device tasks are executed only while Jarvis is visible (Android restricts background activity starts).
    override fun onStart() { super.onStart(); vm.poller.start(lifecycleScope) }
    override fun onStop() { vm.poller.stop(); vm.voice.stopListening(); super.onStop() }
}
