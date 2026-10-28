package ai.jarvis.ultimate.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalUriHandler
import ai.jarvis.ultimate.brain.PRESETS
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

@Composable
fun JarvisTheme(content: @Composable () -> Unit) = MaterialTheme(
    colorScheme = darkColorScheme(primary = Cyan, secondary = Blue, background = Bg, surface = Panel,
        onPrimary = Bg, onBackground = Color(0xFFD8F3FF), onSurface = Color(0xFFD8F3FF)),
    content = content,
)

@Composable
private fun Card(modifier: Modifier = Modifier, title: String? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().background(Panel.copy(alpha = 0.8f), RoundedCornerShape(10.dp))
        .border(1.dp, Cyan.copy(alpha = 0.2f), RoundedCornerShape(10.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        title?.let { Text(it.uppercase(), color = Cyan, fontSize = 12.sp, letterSpacing = 2.sp) }
        content()
    }
}

@Composable
fun Mono(text: String, color: Color = Muted, size: Int = 12) = Text(text, color = color, fontFamily = FontFamily.Monospace, fontSize = size.sp)

// ---- 1. startup ---------------------------------------------------------------------------
@Composable
fun StartupScreen(vm: MainViewModel) {
    Column(Modifier.fillMaxSize().background(Bg).padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text("J.A.R.V.I.S", color = Cyan, fontFamily = FontFamily.Monospace, fontSize = 30.sp, letterSpacing = 8.sp)
        Mono("ULTIMATE AI", size = 11)
        Spacer(Modifier.height(24.dp))
        vm.boot.forEach { Mono(it.text, when (it.ok) { true -> Ok; false -> Amber; null -> Muted }, 13) }
    }
}

@Composable
fun LoginScreen(vm: MainViewModel) {
    var url by rememberSaveable { mutableStateOf(vm.store.backendUrl.ifBlank { "https://" }) }
    var user by rememberSaveable { mutableStateOf(vm.store.username) }
    var pass by remember { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf(vm.store.username) }
    Column(Modifier.fillMaxSize().background(Bg).padding(24.dp).imePadding().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically)) {
        Text("JARVIS", color = Cyan, fontSize = 34.sp, letterSpacing = 6.sp, modifier = Modifier.align(Alignment.CenterHorizontally))
        Card(title = "Use on this phone only") {
            Text("Works right away — no computer or server needed. Memory, approvals and phone actions stay on this phone.")
            OutlinedTextField(name, { name = it }, label = { Text("Your name") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("local_name"))
            Button({ vm.startLocal(name) }, Modifier.fillMaxWidth().testTag("use_local")) { Text("Start Jarvis on this phone") }
        }
        Card(title = if (vm.status?.registrationOpen == true) "Or connect to your Jarvis server" else "Or sign in to your Jarvis server") {
            Mono("Needed for: syncing with the web console and controlling your Windows computer.")
            OutlinedTextField(url, { url = it }, label = { Text("Backend URL") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(user, { user = it }, label = { Text("Username") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pass, { pass = it }, label = { Text("Password (10+ characters)") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
            Button({ vm.login(url, user, pass) }, Modifier.fillMaxWidth()) { Text("Continue") }
            if (vm.loginError.isNotBlank()) Text(vm.loginError, color = Danger)
            Mono("Use HTTPS (e.g. via Tailscale or a reverse proxy). The emulator can use http://10.0.2.2:8765.")
        }
    }
}

// ---- main shell: bottom navigation (Home, Chat, Memory, Devices, More) -----------------------
private val NAV = listOf("home" to ("⌂" to "Home"), "chat" to ("💬" to "Chat"), "memory" to ("◈" to "Memory"),
    "devices" to ("▣" to "Devices"), "more" to ("⋯" to "More"))
private val MORE = listOf("voice" to "Voice Conversation", "ai" to "AI Provider Settings",
    "privacy" to "Privacy & Security", "history" to "Automation History")

@Composable
fun MainScreen(vm: MainViewModel, requestMic: () -> Unit) {
    var route by rememberSaveable { mutableStateOf("home") }
    val state by vm.assistantState.collectAsState()
    val pollState by vm.poller.state.collectAsState()
    Column(Modifier.fillMaxSize().background(Bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            if (route in MORE.map { it.first }) TextButton({ route = "more" }) { Text("‹ Back") }
            StatusDot(if (vm.backendOnline) Ok else Danger, if (vm.backendOnline) "Backend" else "Offline")
            StatusDot(if (vm.status?.provider?.ai == true) Ok else Amber, if (vm.status?.provider?.ai == true) "AI" else "Local cmds")
            StatusDot(if (state == AssistantState.LISTENING) Danger else Muted, if (state == AssistantState.LISTENING) "MIC ON" else "Mic off")
        }
        Box(Modifier.weight(1f).padding(horizontal = 16.dp, vertical = 4.dp)) {
            when (route) {
                "home" -> Dashboard(vm, state, requestMic, pollState) { route = it }
                "voice" -> VoiceScreen(vm, state, requestMic)
                "chat" -> ChatScreen(vm, requestMic)
                "devices" -> DevicesScreen(vm, pollState)
                "memory" -> MemoryScreen(vm)
                "ai" -> ProviderScreen(vm)
                "privacy" -> PrivacyScreen(vm)
                "history" -> HistoryScreen(vm)
                "more" -> MoreScreen { route = it }
            }
        }
        NavigationBar(containerColor = Color(0xFF030A16)) {
            NAV.forEach { (key, v) ->
                val selected = route == key || (key == "more" && route in MORE.map { it.first })
                NavigationBarItem(selected = selected, onClick = { route = key },
                    icon = { Text(v.first, fontSize = 18.sp) }, label = { Text(v.second, fontSize = 11.sp) },
                    colors = NavigationBarItemDefaults.colors(selectedTextColor = Cyan, selectedIconColor = Cyan,
                        unselectedTextColor = Muted, unselectedIconColor = Muted, indicatorColor = Blue.copy(alpha = 0.25f)))
            }
        }
    }
    vm.toast?.let { msg ->
        AlertDialog(onDismissRequest = { vm.toast = null }, confirmButton = { TextButton({ vm.toast = null }) { Text("OK") } },
            text = { Text(msg) }, containerColor = Panel)
    }
}

@Composable
private fun MoreScreen(open: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("More", fontSize = 22.sp)
        MORE.forEach { (key, label) ->
            Row(Modifier.fillMaxWidth().background(Panel, RoundedCornerShape(14.dp)).border(1.dp, Cyan.copy(alpha = 0.18f), RoundedCornerShape(14.dp))
                .clickable { open(key) }.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(label, Modifier.weight(1f)); Text("›", color = Muted, fontSize = 20.sp)
            }
        }
    }
}

@Composable
private fun StatusDot(color: Color, label: String) = Row(verticalAlignment = Alignment.CenterVertically) {
    Box(Modifier.size(8.dp).background(color, CircleShape)); Spacer(Modifier.size(4.dp)); Mono(label, size = 11)
}

@Composable
private fun MicButton(state: AssistantState, requestMic: () -> Unit, big: Boolean = false) {
    val listening = state == AssistantState.LISTENING
    Button(requestMic, shape = CircleShape, modifier = Modifier.size(if (big) 88.dp else 52.dp),
        colors = ButtonDefaults.buttonColors(containerColor = if (listening) Danger.copy(alpha = 0.4f) else Cyan.copy(alpha = 0.15f))) {
        Text(if (listening) "■" else "🎙", fontSize = if (big) 28.sp else 18.sp)
    }
}

@Composable
private fun Composer(vm: MainViewModel, state: AssistantState, requestMic: () -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.imePadding()) {
        MicButton(state, requestMic)
        OutlinedTextField(text, { text = it }, placeholder = { Text("Ask Jarvis…") }, modifier = Modifier.weight(1f).testTag("composer_input"), maxLines = 4)
        Button({ vm.send(text); text = "" }, modifier = Modifier.testTag("send"), enabled = text.isNotBlank() && state != AssistantState.PROCESSING) { Text("Send") }
    }
}

@Composable
private fun PendingList(vm: MainViewModel) {
    if (vm.pending.isEmpty()) { Mono("Nothing waiting."); return }
    vm.pending.forEach { a ->
        Column(Modifier.fillMaxWidth().border(1.dp, Amber.copy(alpha = 0.4f), RoundedCornerShape(8.dp)).padding(10.dp)) {
            Text(a.summary)
            Mono(a.tool)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button({ vm.resolve(a, true) }, Modifier.testTag("approve")) { Text("Approve") }
                OutlinedButton({ vm.resolve(a, false) }) { Text("Deny") }
            }
        }
    }
}

// ---- 2. dashboard ---------------------------------------------------------------------------------
@Composable
fun Dashboard(vm: MainViewModel, state: AssistantState, requestMic: () -> Unit, pollState: String, open: (String) -> Unit) {
    val level by vm.voice.level.collectAsState()
    val hour = remember { java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY) }
    val name = vm.store.username.replaceFirstChar { it.uppercase() }.ifBlank { "there" }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(46.dp).background(Brush.linearGradient(listOf(Color(0xFF1E3A8A), Color(0xFF0E7490))), CircleShape)
                .border(2.dp, Cyan, CircleShape), contentAlignment = Alignment.Center) { Text(name.take(1)) }
            Spacer(Modifier.size(12.dp))
            Column {
                Text(if (hour < 12) "Good Morning," else if (hour < 17) "Good Afternoon," else "Good Evening,", color = Cyan, fontSize = 13.sp)
                Text(name, fontSize = 22.sp)
            }
        }
        Text("I'm JARVIS, your personal AI assistant. How can I help you today?", fontSize = 16.sp)
        if (vm.status?.provider?.ai != true) {
            Row(Modifier.fillMaxWidth().background(Amber.copy(alpha = 0.12f), RoundedCornerShape(12.dp))
                .border(1.dp, Amber.copy(alpha = 0.5f), RoundedCornerShape(12.dp))
                .clickable { open("ai") }.padding(12.dp).testTag("connect_ai_banner"), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("AI not connected", color = Amber)
                    Text("Right now I only understand simple commands. Tap to connect a free AI (Groq/Gemini) — 2 minutes.", fontSize = 13.sp)
                }
                Text("›", color = Amber, fontSize = 22.sp)
            }
        }
        Card {
            JarvisCore(state, level, Modifier.fillMaxWidth().widthIn(max = 360.dp).align(Alignment.CenterHorizontally))
            Text(state.name, color = stateColor(state), fontFamily = FontFamily.Monospace, letterSpacing = 6.sp,
                modifier = Modifier.align(Alignment.CenterHorizontally))
            vm.chat.lastOrNull { it.role == "assistant" }?.let { Text(it.text, color = if (it.isError) Danger else Color.Unspecified, modifier = Modifier.testTag("last_reply")) }
            Composer(vm, state, requestMic)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            listOf("💬" to ("Chat" to "chat"), "🛠" to ("Tools" to "devices"), "◈" to ("Memory" to "memory"), "⚙" to ("Settings" to "privacy")).forEach { (ic, v) ->
                Column(Modifier.weight(1f).background(Panel, RoundedCornerShape(14.dp)).border(1.dp, Cyan.copy(alpha = 0.18f), RoundedCornerShape(14.dp))
                    .clickable { open(v.second) }.padding(vertical = 14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(ic, fontSize = 20.sp); Text(v.first, fontSize = 12.sp)
                }
            }
        }
        Card(title = "Needs your approval") { PendingList(vm) }
        Card(title = "Tool activity") {
            if (vm.activity.isEmpty()) Mono("No tool activity yet.") else vm.activity.take(8).forEach { Mono(it, Color(0xFFD8F3FF)) }
        }
        Card(title = "This phone") { Mono(if (vm.isLocal) "Phone-only mode: actions run directly on this phone" else "Device agent: $pollState") }
    }
}

// ---- 3. voice ---------------------------------------------------------------------------------------
@Composable
fun VoiceScreen(vm: MainViewModel, state: AssistantState, requestMic: () -> Unit) {
    val level by vm.voice.level.collectAsState()
    val partial by vm.voice.partial.collectAsState()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        JarvisCore(state, level, Modifier.fillMaxWidth().widthIn(max = 380.dp))
        Text(if (state == AssistantState.LISTENING) partial.ifBlank { "Listening…" } else state.name, fontSize = 18.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
            MicButton(state, requestMic, big = true)
            OutlinedButton({ vm.voice.stopSpeaking() }) { Text("Stop speaking") }
        }
        if (!vm.voice.recognitionAvailable) Text("Speech recognition isn't available on this phone. Use text chat.", color = Amber)
        Card(title = "Voice settings") {
            val lang = vm.settings?.get("voice")?.jsonObject?.get("lang")?.jsonPrimitive?.content ?: "en-IN"
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("en-IN" to "English", "hi-IN" to "हिन्दी/Hinglish").forEach { (code, label) ->
                    if (lang == code) Button({}) { Text(label) } else OutlinedButton({ vm.setVoice(code, vm.voice.speechRate) }) { Text(label) }
                }
            }
            var rate by remember { mutableFloatStateOf(vm.voice.speechRate) }
            Mono("Speech rate ${"%.1f".format(rate)}×")
            Slider(rate, { rate = it }, valueRange = 0.5f..2f, onValueChangeFinished = { vm.setVoice(lang, rate) })
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(vm.speakReplies, { vm.speakReplies = it }); Spacer(Modifier.size(8.dp)); Text("Speak replies aloud")
            }
            Mono("Push-to-talk only. Android's recognizer may send audio to Google. There is no always-on wake word on Android (see docs).")
        }
    }
}

// ---- 4. chat --------------------------------------------------------------------------------------------
@Composable
fun ChatScreen(vm: MainViewModel, requestMic: () -> Unit) {
    val state by vm.assistantState.collectAsState()
    val list = rememberLazyListState()
    LaunchedEffect(vm.chat.size) { if (vm.chat.isNotEmpty()) list.animateScrollToItem(vm.chat.lastIndex) }
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Conversation", color = Cyan, modifier = Modifier.weight(1f)); TextButton({ vm.newConversation() }) { Text("New") }
        }
        LazyColumn(Modifier.weight(1f), state = list, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(vm.chat) { m ->
                val mine = m.role == "user"
                Box(Modifier.fillMaxWidth(), contentAlignment = if (mine) Alignment.CenterEnd else Alignment.CenterStart) {
                    Text(m.text, modifier = Modifier.widthIn(max = 300.dp)
                        .background(if (mine) Blue.copy(alpha = 0.25f) else Cyan.copy(alpha = 0.08f), RoundedCornerShape(10.dp))
                        .border(1.dp, if (m.isError) Danger else Cyan.copy(alpha = 0.2f), RoundedCornerShape(10.dp)).padding(10.dp))
                }
            }
        }
        Composer(vm, state, requestMic)
    }
}

// ---- 5 + 10. devices ---------------------------------------------------------------------------------------
@Composable
fun DevicesScreen(vm: MainViewModel, pollState: String) {
    LaunchedEffect(Unit) { vm.refreshDevices() }
    var confirmPair by remember { mutableStateOf(false) }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (vm.isLocal) Card(title = "Phone-only mode") {
            Text("Jarvis controls this phone directly. To also control a Windows computer or sync with the web console, sign out (Privacy → Sign out) and connect to your Jarvis server.")
        } else Card(title = "This phone") {
            Mono("Agent: $pollState", Color(0xFFD8F3FF))
            if (vm.store.deviceId == null) Button({ confirmPair = true }) { Text("Let Jarvis control this phone") }
            else OutlinedButton({ vm.unpairThisPhone() }) { Text("Unpair this phone") }
            Mono("Phone actions run only while this app is open. Calls and SMS are never sent automatically — you press Call/Send.")
        }
        Card(title = "Connected devices") {
            if (vm.devices.isEmpty()) Mono("No devices paired yet.")
            vm.devices.forEach { d ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("${d.name}  ·  ${d.platform}")
                        Mono(if (d.status == "approved") (if (d.online) "online" else "offline") else d.status,
                            if (d.online) Ok else if (d.status == "revoked") Danger else Amber)
                    }
                    if (d.status == "pending") TextButton({ vm.setDevice(d, true) }) { Text("Approve") }
                    if (d.status != "revoked") TextButton({ vm.setDevice(d, false) }) { Text("Revoke", color = Danger) }
                }
            }
            Button({ vm.newPairingCode() }) { Text("Pairing code for a computer") }
            vm.pairingCode?.let { Text(it.chunked(4).joinToString("-"), color = Cyan, fontFamily = FontFamily.Monospace, fontSize = 28.sp, letterSpacing = 6.sp) }
            Mono("Enter the code in Jarvis Desktop, then approve the computer above. Codes expire in 10 minutes.")
        }
    }
    if (confirmPair) AlertDialog(onDismissRequest = { confirmPair = false }, containerColor = Panel,
        title = { Text("Allow Jarvis to act on this phone?") },
        text = { Text("Jarvis will be able to open apps, links, settings screens, the camera and the dialer/SMS composer on this phone while the app is open. You can revoke this any time.") },
        confirmButton = { Button({ confirmPair = false; vm.registerThisPhone() }) { Text("Allow") } },
        dismissButton = { TextButton({ confirmPair = false }) { Text("Cancel") } })
}

// ---- 6. memory ------------------------------------------------------------------------------------------------
@Composable
fun MemoryScreen(vm: MainViewModel) {
    LaunchedEffect(Unit) { vm.loadMemories() }
    var q by rememberSaveable { mutableStateOf("") }
    var add by rememberSaveable { mutableStateOf("") }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Card(title = "Saved memory") {
            Mono("Saved memory persists across devices. The current chat is temporary context. Passwords, OTPs, card and ID numbers are refused.")
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(q, { q = it }, label = { Text("Search") }, modifier = Modifier.weight(1f), singleLine = true)
                TextButton({ vm.loadMemories(q) }) { Text("Go") }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(add, { add = it }, label = { Text("Remember…") }, modifier = Modifier.weight(1f))
                TextButton({ vm.addMemory(add, "preference"); add = "" }, enabled = add.isNotBlank()) { Text("Save") }
            }
            if (vm.memories.isEmpty()) Mono("No saved memories.")
            vm.memories.forEach { m ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { Text(m.content); Mono("${m.kind} · #${m.id}") }
                    TextButton({ vm.deleteMemory(m) }) { Text("Delete", color = Danger) }
                }
            }
        }
    }
}

// ---- 7. AI provider --------------------------------------------------------------------------------------------
@Composable
fun ProviderScreen(vm: MainViewModel) {
    if (vm.isLocal) { LocalProviderScreen(vm); return }
    val s = vm.status
    Card(title = "AI provider") {
        if (s == null) { Mono("Not connected."); return@Card }
        Mono("Mode: ${if (s.provider.ai) "AI model" else "Local command mode (no AI)"}", Color(0xFFD8F3FF), 14)
        Mono("Provider: ${s.provider.name}", Color(0xFFD8F3FF), 14)
        Mono("Model: ${s.provider.model}", Color(0xFFD8F3FF), 14)
        Mono("Web search: ${if (s.search.configured) s.search.name else "not configured"}", Color(0xFFD8F3FF), 14)
        Mono("Providers and API keys are configured only on your backend server, never in this app. Change JARVIS_LLM_PROVIDER / JARVIS_LLM_MODEL there and restart it.")
    }
}

@Composable
private fun LocalProviderScreen(vm: MainViewModel) {
    var provider by rememberSaveable { mutableStateOf(vm.store.llmProvider) }
    var baseUrl by rememberSaveable { mutableStateOf(vm.store.llmBaseUrl) }
    var model by rememberSaveable { mutableStateOf(vm.store.llmModel) }
    var key by remember { mutableStateOf("") }
    var preset by rememberSaveable { mutableStateOf(PRESETS.firstOrNull { it.baseUrl == vm.store.llmBaseUrl && it.provider == vm.store.llmProvider }?.key ?: "") }
    val uri = LocalUriHandler.current
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Card(title = "Connect an AI brain") {
            Text("Without AI, Jarvis only knows simple commands. Pick a provider — Groq and Gemini have free keys.")
            PRESETS.forEach { p ->
                Row(Modifier.fillMaxWidth().clickable {
                    preset = p.key; provider = p.provider; baseUrl = p.baseUrl; model = ""; vm.models.clear(); vm.modelsMsg = ""
                }.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = preset == p.key, onClick = { preset = p.key; provider = p.provider; baseUrl = p.baseUrl; model = ""; vm.models.clear() })
                    Column(Modifier.weight(1f)) { Text(p.label); Mono(p.note) }
                }
            }
            Row(Modifier.fillMaxWidth().clickable { preset = ""; provider = "local-rules" }.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected = provider == "local-rules", onClick = { preset = ""; provider = "local-rules" })
                Text("No AI (offline simple commands)")
            }
        }
        if (provider != "local-rules") Card(title = "Step 2 — key and model") {
            PRESETS.firstOrNull { it.key == preset }?.let { p ->
                OutlinedButton({ uri.openUri(p.keyUrl) }) { Text("Get a key from ${p.label.substringBefore(" (")} ↗") }
            }
            OutlinedTextField(key, { key = it }, label = { Text(if (vm.store.llmApiKey.isBlank()) "Paste API key" else "API key (saved — leave blank to keep)") },
                singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth().testTag("api_key"))
            if (preset == "" || preset == "ollama" || provider == "openai-compatible" && PRESETS.none { it.baseUrl == baseUrl })
                OutlinedTextField(baseUrl, { baseUrl = it }, label = { Text("Base URL") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button({ vm.loadModels(provider, baseUrl, key) }, Modifier.fillMaxWidth()) { Text("Load models") }
            if (vm.modelsMsg.isNotBlank()) Mono(vm.modelsMsg, Color(0xFFD8F3FF), 13)
            vm.models.take(40).forEach { m ->
                Row(Modifier.fillMaxWidth().clickable { model = m }.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = model == m, onClick = { model = m }); Text(m, fontSize = 14.sp)
                }
            }
            OutlinedTextField(model, { model = it }, label = { Text("Model") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Mono("Your key is stored encrypted on this phone only and sent only to the provider you chose.")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Button({ vm.saveLlm(provider, baseUrl, model, key); key = "" }) { Text("Save") }
            OutlinedButton({ vm.testLlm() }) { Text("Test Connection") }
        }
        if (vm.providerTest.isNotBlank()) Mono(vm.providerTest, if (vm.providerTest.startsWith("Connected")) Ok else Amber, 13)
        val p = vm.status?.provider
        Mono("Active: ${if (p?.ai == true) "${p.name} · ${p.model}" else "no AI — simple commands only"}", Color(0xFFD8F3FF), 13)
    }
}

// ---- 8. privacy ---------------------------------------------------------------------------------------------------
@Composable
fun PrivacyScreen(vm: MainViewModel) {
    var confirmClear by remember { mutableStateOf(false) }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Card(title = "Permissions (the AI cannot change these)") {
            (vm.status?.permissions ?: emptyMap()).forEach { (key, label) ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(label, Modifier.weight(1f)); Switch(vm.permission(key), { vm.setPermission(key, it) })
                }
            }
        }
        Card(title = "Memory & data") {
            Row(verticalAlignment = Alignment.CenterVertically) { Text("Use and save memory", Modifier.weight(1f)); Switch(vm.bool("memory_enabled"), { vm.setSetting("memory_enabled", it) }) }
            Row(verticalAlignment = Alignment.CenterVertically) { Text("Ask before saving a memory", Modifier.weight(1f)); Switch(vm.bool("memory_require_approval"), { vm.setSetting("memory_require_approval", it) }) }
            OutlinedButton({ confirmClear = true }) { Text("Clear conversation history", color = Danger) }
            OutlinedButton({ vm.signOut() }) { Text("Sign out") }
        }
    }
    if (confirmClear) AlertDialog(onDismissRequest = { confirmClear = false }, containerColor = Panel,
        text = { Text("Delete all conversations? Saved memories are kept.") },
        confirmButton = { Button({ confirmClear = false; vm.clearHistory() }) { Text("Delete") } },
        dismissButton = { TextButton({ confirmClear = false }) { Text("Cancel") } })
}

// ---- 9. history ------------------------------------------------------------------------------------------------------
@Composable
fun HistoryScreen(vm: MainViewModel) {
    LaunchedEffect(Unit) { vm.loadAudit() }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        item { Row { Text("Automation history", color = Cyan, modifier = Modifier.weight(1f)); TextButton({ vm.loadAudit() }) { Text("Refresh") } } }
        items(vm.audit) { a ->
            Column(Modifier.fillMaxWidth().border(1.dp, Cyan.copy(alpha = 0.15f), RoundedCornerShape(6.dp)).padding(8.dp)) {
                Text("${a.event}${a.tool?.let { " · $it" } ?: ""}")
                Mono("${a.createdAt} · ${a.actor} · ${a.status}", if (a.status == "ok") Ok else if (a.status in setOf("awaiting", "pending", "queued")) Amber else Danger)
            }
        }
    }
}

