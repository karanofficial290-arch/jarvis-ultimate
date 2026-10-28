package ai.jarvis.ultimate

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Runs the real APK on an emulator: start phone-only mode, chat, use a tool, approve a memory. */
@OptIn(ExperimentalTestApi::class)
@RunWith(AndroidJUnit4::class)
class PhoneOnlyModeTest {
    @get:Rule val rule = createAndroidComposeRule<MainActivity>()

    private fun lastReply(): String =
        rule.onNodeWithTag("last_reply").fetchSemanticsNode().config[SemanticsProperties.Text].joinToString { it.text }

    private fun say(text: String) {
        rule.onNodeWithTag("composer_input").performTextInput(text)
        rule.onNodeWithTag("send").performClick()
    }

    private fun waitReply(predicate: (String) -> Boolean) = rule.waitUntil(20_000) {
        runCatching { predicate(lastReply()) }.getOrDefault(false)
    }

    private fun dismissDialog() {
        if (rule.onAllNodes(hasText("OK")).fetchSemanticsNodes().isNotEmpty()) rule.onNodeWithText("OK").performClick()
    }

    @Test fun phoneOnlyAssistantWorksEndToEnd() {
        rule.waitUntilAtLeastOneExists(hasTestTag("use_local"), 20_000)
        rule.onNodeWithTag("local_name").performTextInput("Rahul")
        rule.onNodeWithTag("use_local").performClick()
        rule.waitUntilAtLeastOneExists(hasTestTag("composer_input"), 20_000)
        rule.onNodeWithText("Rahul").assertExists()                     // greeting uses the name

        say("Hey Jarvis, how are you?")
        waitReply { it == "I'm ready, sir. How can I help you?" }

        say("what time is it")
        waitReply { it.startsWith("It's ") }

        say("battery")
        waitReply { it.startsWith("Battery is at") || it.startsWith("That didn't work") }

        say("Remember that I prefer chai over coffee")
        waitReply { it.startsWith("I need your confirmation first") }
        rule.waitUntilAtLeastOneExists(hasTestTag("approve"), 10_000)
        rule.onNodeWithTag("approve").performClick()
        waitReply { it.startsWith("Saved to memory") }
        dismissDialog()

        say("what do you remember about chai")
        waitReply { it.contains("I prefer chai over coffee") }

        say("remember that my password is tiger12345")
        waitReply { it.startsWith("That didn't work: I won't save that because it looks like a password") }
    }
}
