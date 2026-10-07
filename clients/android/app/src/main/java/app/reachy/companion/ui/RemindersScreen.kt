package app.reachy.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForwardIos
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.outlined.RadioButtonUnchecked
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.reachy.companion.AppViewModel
import app.reachy.companion.data.Reminder
import app.reachy.companion.data.Task
import app.reachy.companion.data.completedReminders
import app.reachy.companion.data.isOverdue
import app.reachy.companion.data.pendingReminders
import app.reachy.companion.data.reminderWhen
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset

private val Red = Color(0xFFFF453A)
private val Purple = Color(0xFFBF5AF2)
private enum class Screen { Home, Todo, Scheduled }

/** The Apple-Reminders-style area: a lists home, then the To Do list and the timed Reminders list. */
@Composable
fun RemindersScreen(model: AppViewModel, modifier: Modifier = Modifier) {
    var screen by remember { mutableStateOf(Screen.Home) }
    LaunchedEffect(Unit) { model.loadReminders() }
    val wide = isWide()
    BackHandler(screen != Screen.Home && !wide) { screen = Screen.Home }
    if (wide) {
        // Unfolded or landscape: the lists stay on the left and the chosen list fills the right (To Do until one is chosen).
        val shown = if (screen == Screen.Home) Screen.Todo else screen
        TwoPane(modifier, listWidth = 320, list = { Home(model, onOpen = { screen = it }, stacked = true) }, detail = {
            Column(Modifier.fillMaxSize()) {
                when (shown) {
                    Screen.Scheduled -> ReminderList(model, onBack = null)
                    else -> TodoList(model, onBack = null)
                }
            }
        })
        return
    }
    Column(modifier.fillMaxSize()) {
        when (screen) {
            Screen.Home -> Home(model, onOpen = { screen = it })
            Screen.Todo -> TodoList(model) { screen = Screen.Home }
            Screen.Scheduled -> ReminderList(model) { screen = Screen.Home }
        }
    }
}

@Composable
private fun Home(model: AppViewModel, onOpen: (Screen) -> Unit, stacked: Boolean = false) {
    val openTasks = model.tasks.count { !it.done }
    val pending = model.reminders.count { !it.done }
    val overdue = model.reminders.count { isOverdue(it) }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Reminders", fontSize = 34.sp, fontWeight = FontWeight.Bold)
        ErrorLine(model.listError)
        val todo: @Composable (Modifier) -> Unit = { m -> Tile("To Do", openTasks, Red, Icons.AutoMirrored.Filled.List, m) { onOpen(Screen.Todo) } }
        val scheduled: @Composable (Modifier) -> Unit = { m -> Tile("Scheduled", pending, Purple, Icons.Default.Schedule, m, note = if (overdue > 0) "$overdue overdue" else null) { onOpen(Screen.Scheduled) } }
        if (stacked) { todo(Modifier.fillMaxWidth()); scheduled(Modifier.fillMaxWidth()) }
        else Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { todo(Modifier.weight(1f)); scheduled(Modifier.weight(1f)) }
    }
}

@Composable
private fun Tile(title: String, count: Int, color: Color, icon: androidx.compose.ui.graphics.vector.ImageVector, modifier: Modifier, note: String? = null, onClick: () -> Unit) {
    Column(
        modifier.background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f), RoundedCornerShape(16.dp)).clickable(onClick = onClick).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(34.dp).background(color, CircleShape), contentAlignment = Alignment.Center) { Icon(icon, null, Modifier.size(20.dp), tint = Color.White) }
            Box(Modifier.weight(1f))
            Text(count.toString(), fontSize = 28.sp, fontWeight = FontWeight.Bold)
        }
        Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
        if (note != null) Text(note, style = MaterialTheme.typography.bodySmall, color = Red)
    }
}

@Composable
private fun ListHeader(title: String, color: Color, onBack: (() -> Unit)?) {
    Column(Modifier.padding(horizontal = 8.dp).padding(top = if (onBack == null) 16.dp else 0.dp)) {
        if (onBack != null) TextButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, null, tint = color); Text(" Lists", color = color) }
        Text(title, Modifier.padding(start = 8.dp, bottom = 8.dp), fontSize = 34.sp, fontWeight = FontWeight.Bold, color = color)
    }
}

/** A round check circle: empty, or filled once done. */
@Composable
private fun Circle(done: Boolean, color: Color, enabled: Boolean = true, onClick: () -> Unit) {
    Icon(
        if (done) Icons.Filled.CheckCircle else Icons.Outlined.RadioButtonUnchecked, if (done) "Completed" else "Mark complete",
        Modifier.size(28.dp).clickable(enabled = enabled, onClick = onClick), tint = if (done) MaterialTheme.colorScheme.outline else color.copy(alpha = 0.8f),
    )
}

/** Swipe left to delete, as in the Reminders app. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SwipeToDelete(onDelete: () -> Unit, content: @Composable () -> Unit) {
    val state = rememberSwipeToDismissBoxState(confirmValueChange = { if (it == SwipeToDismissBoxValue.EndToStart) { onDelete(); true } else false })
    SwipeToDismissBox(
        state, enableDismissFromStartToEnd = false,
        backgroundContent = { Box(Modifier.fillMaxSize().background(Red).padding(end = 20.dp), contentAlignment = Alignment.CenterEnd) { Icon(Icons.Default.Delete, "Delete", tint = Color.White) } },
    ) { Box(Modifier.background(MaterialTheme.colorScheme.background)) { content() } }
}

@Composable
private fun CompletedToggle(count: Int, shown: Boolean, onToggle: () -> Unit) {
    if (count > 0) Text(
        "$count Completed · ${if (shown) "Hide" else "Show"}",
        Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(horizontal = 16.dp, vertical = 14.dp),
        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline,
    )
}

@Composable
private fun NewButton(color: Color, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(26.dp).background(color, CircleShape), contentAlignment = Alignment.Center) { Icon(Icons.Default.Add, null, Modifier.size(18.dp), tint = Color.White) }
        Text("  New Reminder", color = color, fontWeight = FontWeight.SemiBold)
    }
}

// --- To Do ---------------------------------------------------------------------------------------------------

@Composable
private fun TodoList(model: AppViewModel, onBack: (() -> Unit)?) {
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<String?>(null) }
    var showDone by remember { mutableStateOf(false) }
    val open = model.tasks.filter { !it.done }
    val done = model.tasks.filter { it.done }
    Column(Modifier.fillMaxSize().imePadding()) {
        ListHeader("To Do", Red, onBack)
        ErrorLine(model.listError)
        LazyColumn(Modifier.weight(1f)) {
            items(open, key = { it.id }) { task -> TaskRow(model, task, editing == task.id, onEdit = { editing = task.id }, onEditDone = { editing = null }) }
            if (adding) item(key = "new") {
                NewTaskRow(onAdd = { text -> model.addTask(text) }, onClose = { adding = false })
            }
            item(key = "completed") { CompletedToggle(done.size, showDone) { showDone = !showDone } }
            if (showDone) items(done, key = { "d-" + it.id }) { task -> TaskRow(model, task, false, onEdit = {}, onEditDone = {}) }
        }
        NewButton(Red) { adding = true }
    }
}

@Composable
private fun TaskRow(model: AppViewModel, task: Task, editing: Boolean, onEdit: () -> Unit, onEditDone: () -> Unit) {
    SwipeToDelete({ model.deleteTask(task) }) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
            Circle(task.done, Red) { model.toggleTask(task) }
            Box(Modifier.weight(1f).padding(start = 12.dp)) {
                if (editing) {
                    var text by remember { mutableStateOf(task.text) }
                    val focus = remember { FocusRequester() }
                    val finish = { val next = text.trim(); onEditDone(); if (next.isNotEmpty() && next != task.text) model.editTask(task, next) }
                    var focused by remember { mutableStateOf(false) }   // a blur only counts once the field has had focus
                    LaunchedEffect(Unit) { focus.requestFocus() }
                    BasicTextField(
                        text, { text = it }, Modifier.fillMaxWidth().focusRequester(focus).onFocusChanged { if (it.isFocused) focused = true else if (focused && editing) finish() },
                        textStyle = TextStyle(color = MaterialTheme.colorScheme.onSurface, fontSize = 17.sp), cursorBrush = SolidColor(Red),
                        singleLine = true, keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { finish() }),
                    )
                } else Text(
                    task.text, Modifier.fillMaxWidth().clickable(enabled = !task.done, onClick = onEdit), fontSize = 17.sp,
                    textDecoration = if (task.done) TextDecoration.LineThrough else null,
                    color = if (task.done) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.onSurface,
                )
            }
        }
        androidx.compose.material3.HorizontalDivider(Modifier.padding(start = 56.dp))
    }
}

@Composable
private fun NewTaskRow(onAdd: (String) -> Unit, onClose: () -> Unit) {
    var text by remember { mutableStateOf("") }
    val focus = remember { FocusRequester() }
    var focused by remember { mutableStateOf(false) }   // a blur only counts once the field has had focus
    LaunchedEffect(Unit) { focus.requestFocus() }
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
        Icon(Icons.Outlined.RadioButtonUnchecked, null, Modifier.size(28.dp), tint = MaterialTheme.colorScheme.outline)
        BasicTextField(
            text, { text = it }, Modifier.weight(1f).padding(start = 12.dp).focusRequester(focus).onFocusChanged { if (it.isFocused) focused = true else if (focused && text.isBlank()) onClose() },
            textStyle = TextStyle(color = MaterialTheme.colorScheme.onSurface, fontSize = 17.sp), cursorBrush = SolidColor(Red),
            singleLine = true, keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { if (text.isBlank()) onClose() else { onAdd(text.trim()); text = "" } }),
            decorationBox = { inner -> Box { if (text.isEmpty()) Text("New reminder", color = MaterialTheme.colorScheme.outline, fontSize = 17.sp); inner() } },
        )
    }
}

// --- Reminders (timed) ---------------------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReminderList(model: AppViewModel, onBack: (() -> Unit)?) {
    var showDone by remember { mutableStateOf(false) }
    var creating by remember { mutableStateOf(false) }
    val pending = pendingReminders(model.reminders)
    val done = completedReminders(model.reminders)
    Column(Modifier.fillMaxSize()) {
        ListHeader("Reminders", Purple, onBack)
        ErrorLine(model.listError)
        if (model.reminders.isEmpty()) Text("No reminders.", Modifier.padding(16.dp))
        LazyColumn(Modifier.weight(1f)) {
            items(pending, key = { it.id }) { ReminderRow(model, it) }
            item(key = "completed") { CompletedToggle(done.size, showDone) { showDone = !showDone } }
            if (showDone) items(done, key = { "d-" + it.id }) { ReminderRow(model, it) }
        }
        NewButton(Purple) { creating = true }
    }
    if (creating) NewReminderSheet(onClose = { creating = false }) { text, whenIso -> model.addReminder(text, whenIso); creating = false }
}

@Composable
private fun ReminderRow(model: AppViewModel, reminder: Reminder) {
    val overdue = isOverdue(reminder)
    SwipeToDelete({ model.deleteReminder(reminder.id) }) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
            // The hub can complete a reminder but not reopen one, so a ticked circle stays ticked.
            Circle(reminder.done, Purple, enabled = !reminder.done) { model.completeReminder(reminder.id) }
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(
                    reminder.text, fontSize = 17.sp, textDecoration = if (reminder.done) TextDecoration.LineThrough else null,
                    color = if (reminder.done) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    reminderWhen(reminder.dueAt) + if (overdue) " · due" else "", style = MaterialTheme.typography.bodySmall,
                    color = if (overdue) Red else MaterialTheme.colorScheme.outline, fontWeight = if (overdue) FontWeight.SemiBold else null,
                )
            }
        }
        androidx.compose.material3.HorizontalDivider(Modifier.padding(start = 56.dp))
    }
}

/** New Reminder: a title with a date and a time, as on the iPhone. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NewReminderSheet(onClose: () -> Unit, onAdd: (String, String) -> Unit) {
    val soon = remember { LocalDateTime.now().plusHours(1).withMinute(0).withSecond(0).withNano(0) }
    var title by remember { mutableStateOf("") }
    var date by remember { mutableStateOf(soon.toLocalDate()) }
    var hour by remember { mutableStateOf(soon.hour) }
    var minute by remember { mutableStateOf(soon.minute) }
    var pickDate by remember { mutableStateOf(false) }
    var pickTime by remember { mutableStateOf(false) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    ModalBottomSheet(onClose, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 24.dp).imePadding()) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClose) { Text("Cancel", color = Purple) }
                Text("New Reminder", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                TextButton({ onAdd(title.trim(), LocalDateTime.of(date, java.time.LocalTime.of(hour, minute)).atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()) }, enabled = title.isNotBlank()) {
                    Text("Add", color = Purple, fontWeight = FontWeight.Bold)
                }
            }
            Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)).padding(horizontal = 16.dp)) {
                BasicTextField(
                    title, { title = it.take(500) }, Modifier.fillMaxWidth().padding(vertical = 14.dp).focusRequester(focus),
                    textStyle = TextStyle(color = MaterialTheme.colorScheme.onSurface, fontSize = 17.sp), cursorBrush = SolidColor(Purple), singleLine = true,
                    decorationBox = { inner -> Box { if (title.isEmpty()) Text("Title", color = MaterialTheme.colorScheme.outline, fontSize = 17.sp); inner() } },
                )
                androidx.compose.material3.HorizontalDivider()
                Row(Modifier.fillMaxWidth().clickable { pickDate = true }.padding(vertical = 14.dp)) {
                    Text("Date", Modifier.weight(1f)); Text(app.reachy.companion.data.reminderWhen(LocalDateTime.of(date, java.time.LocalTime.of(hour, minute)).atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()).substringBefore(","), color = Purple)
                }
                androidx.compose.material3.HorizontalDivider()
                Row(Modifier.fillMaxWidth().clickable { pickTime = true }.padding(vertical = 14.dp)) {
                    Text("Time", Modifier.weight(1f)); Text("%d:%02d %s".format(if (hour % 12 == 0) 12 else hour % 12, minute, if (hour >= 12) "PM" else "AM"), color = Purple)
                }
            }
        }
    }
    if (pickDate) {
        val state = rememberDatePickerState(initialSelectedDateMillis = date.atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli())
        DatePickerDialog(
            { pickDate = false },
            confirmButton = { TextButton({ state.selectedDateMillis?.let { date = java.time.Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate() }; pickDate = false }) { Text("OK") } },
            dismissButton = { TextButton({ pickDate = false }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
    if (pickTime) {
        val state = rememberTimePickerState(initialHour = hour, initialMinute = minute)
        AlertDialog(
            { pickTime = false }, text = { TimePicker(state) },
            confirmButton = { TextButton({ hour = state.hour; minute = state.minute; pickTime = false }) { Text("OK") } },
            dismissButton = { TextButton({ pickTime = false }) { Text("Cancel") } },
        )
    }
}
