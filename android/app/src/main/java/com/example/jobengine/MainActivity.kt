package com.example.jobengine

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.PasswordVisualTransformation
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class JobItem(
    val id: Int, val company: String, val title: String, val location: String,
    val url: String, val score: Double, val status: String,
    val reasons: List<String>, val gaps: List<String>
)

data class ApplicationItem(
    val jobId: Int, val company: String, val title: String, val status: String,
    val followUp: String, val url: String
)

class JobEngineApi(private val base: String, private val username: String, private val password: String) {
    private fun request(method: String, path: String, payload: String? = null): String {
        val root = base.trim().trimEnd('/')
        require(root.startsWith("http://") || root.startsWith("https://")) { "Server URL must start with http:// or https://" }
        val connection = (URL(root + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10000
            readTimeout = 60000
            setRequestProperty("Accept", "application/json")
            if (username.isNotBlank() || password.isNotBlank()) {
                val token = Base64.encodeToString("$username:$password".toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
                setRequestProperty("Authorization", "Basic $token")
            }
            if (payload != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (payload != null) connection.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                val detail = runCatching { JSONObject(body).optString("detail") }.getOrNull().orEmpty()
                throw IllegalStateException(if (detail.isNotBlank()) detail else "Server returned HTTP $status")
            }
            return body
        } finally {
            connection.disconnect()
        }
    }

    private suspend fun get(path: String) = withContext(Dispatchers.IO) { request("GET", path) }
    private suspend fun post(path: String, body: String? = null) = withContext(Dispatchers.IO) { request("POST", path, body) }

    suspend fun health() { get("/health") }
    suspend fun jobs(): List<JobItem> {
        val array = JSONArray(get("/api/jobs"))
        return (0 until array.length()).map { i ->
            val j = array.getJSONObject(i)
            JobItem(j.optInt("id"), j.optString("company"), j.optString("title"), j.optString("location"),
                j.optString("url"), j.optDouble("score"), j.optString("status"), j.stringList("reasons"), j.stringList("gaps"))
        }
    }
    suspend fun applications(): List<ApplicationItem> {
        val array = JSONArray(get("/applications"))
        return (0 until array.length()).map { i ->
            val a = array.getJSONObject(i)
            ApplicationItem(a.optInt("job_id"), a.optString("company"), a.optString("title"),
                a.optString("status"), a.optString("follow_up"), a.optString("url"))
        }
    }
    suspend fun approve(id: Int) = post("/jobs/$id/approve")
    suspend fun reject(id: Int) = post("/jobs/$id/reject")
    suspend fun prepare() = post("/run-batch")
    suspend fun updateStatus(id: Int, status: String) = post(
        "/applications/$id/status", JSONObject().put("status", status).toString()
    )
    suspend fun addJob(company: String, title: String, url: String, location: String, description: String) {
        val job = JSONObject().put("source", "android").put("company", company).put("title", title)
            .put("url", url).put("location", location).put("description", description)
        post("/jobs", JSONArray().put(job).toString())
    }
    suspend fun review(id: Int): JSONObject = JSONObject(post("/jobs/$id/agent-review")).getJSONObject("review")

    private fun JSONObject.stringList(key: String): List<String> {
        val array = optJSONArray(key) ?: return emptyList()
        return (0 until array.length()).map { array.optString(it) }
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { JobEngineApp() } }
    }
}

@Composable
fun JobEngineApp() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("job-engine", Context.MODE_PRIVATE) }
    var baseUrl by remember { mutableStateOf(prefs.getString("base_url", "http://10.0.2.2:8000") ?: "http://10.0.2.2:8000") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var tab by remember { mutableStateOf(0) }
    var jobs by remember { mutableStateOf(emptyList<JobItem>()) }
    var applications by remember { mutableStateOf(emptyList<ApplicationItem>()) }
    var message by remember { mutableStateOf("Connect to your running Python backend in Settings.") }
    var busy by remember { mutableStateOf(false) }
    var review by remember { mutableStateOf<String?>(null) }
    var company by remember { mutableStateOf("") }
    var title by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var location by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    fun api() = JobEngineApi(baseUrl, username, password)
    suspend fun refresh() {
        api().health()
        jobs = api().jobs()
        applications = api().applications()
        message = "Connected · ${jobs.size} jobs · ${applications.size} prepared applications"
    }
    fun execute(action: suspend () -> Unit) {
        scope.launch {
            busy = true
            try { action() } catch (e: Exception) { message = e.message ?: "Request failed" }
            finally { busy = false }
        }
    }

    if (review != null) {
        AlertDialog(
            onDismissRequest = { review = null },
            title = { Text("AI job review") },
            text = { Text(review!!, modifier = Modifier.verticalScroll(rememberScrollState())) },
            confirmButton = { TextButton(onClick = { review = null }) { Text("Close") } },
        )
    }

    Scaffold(bottomBar = {
        NavigationBar {
            listOf("Matches", "Add job", "Applications", "Settings").forEachIndexed { index, label ->
                NavigationBarItem(selected = tab == index, onClick = { tab = index },
                    icon = { Text(listOf("▦", "+", "✓", "⚙")[index]) }, label = { Text(label) })
            }
        }
    }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp, vertical = 10.dp)) {
            Text("Job Engine", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text(message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary)
            Spacer(Modifier.height(10.dp))
            when (tab) {
                0 -> MatchesScreen(jobs, busy,
                    onRefresh = { execute { refresh() } },
                    onApprove = { id -> execute { api().approve(id); refresh() } },
                    onReject = { id -> execute { api().reject(id); refresh() } },
                    onPrepare = { execute { val result = JSONObject(api().prepare()); refresh(); message = "Prepared ${result.optInt("queued")} application packet(s)." } },
                    onReview = { id -> execute { review = api().review(id).toString(2) } },
                    onOpen = { jobUrl -> context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(jobUrl))) })
                1 -> AddJobScreen(company, { company = it }, title, { title = it }, url, { url = it },
                    location, { location = it }, description, { description = it }, busy) {
                    execute {
                        api().addJob(company.trim(), title.trim(), url.trim(), location.trim(), description.trim())
                        company = ""; title = ""; url = ""; location = ""; description = ""
                        refresh(); tab = 0
                    }
                }
                2 -> ApplicationsScreen(applications, busy,
                    onRefresh = { execute { refresh() } },
                    onStatus = { id, status -> execute { api().updateStatus(id, status); refresh() } },
                    onOpen = { jobUrl -> context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(jobUrl))) })
                else -> SettingsScreen(baseUrl, { baseUrl = it }, username, { username = it }, password,
                    { password = it }, busy, onSave = {
                        prefs.edit().putString("base_url", baseUrl.trim().trimEnd('/')).apply()
                        execute { refresh() }
                    })
            }
        }
    }
}

@Composable
private fun MatchesScreen(
    jobs: List<JobItem>, busy: Boolean, onRefresh: () -> Unit, onApprove: (Int) -> Unit,
    onReject: (Int) -> Unit, onPrepare: () -> Unit, onReview: (Int) -> Unit, onOpen: (String) -> Unit
) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = onRefresh, enabled = !busy) { Text("Refresh") }
        Button(onClick = onPrepare, enabled = !busy) { Text("Prepare approved") }
    }
    Spacer(Modifier.height(8.dp))
    if (busy) CircularProgressIndicator()
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(jobs, key = { it.id }) { job ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(job.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text("${job.company} · ${job.location}")
                    Text("Score ${job.score.toInt()} · ${job.status}", color = MaterialTheme.colorScheme.primary)
                    if (job.reasons.isNotEmpty()) Text(job.reasons.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                    if (job.gaps.isNotEmpty()) Text("Skills to learn: ${job.gaps.joinToString()}", style = MaterialTheme.typography.bodySmall)
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (job.status in listOf("AWAITING_APPROVAL", "LOW_MATCH")) Button(onClick = { onApprove(job.id) }, enabled = !busy) { Text("Approve") }
                            if (job.status in listOf("AWAITING_APPROVAL", "LOW_MATCH", "APPROVED")) OutlinedButton(onClick = { onReject(job.id) }, enabled = !busy) { Text("Reject") }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedButton(onClick = { onReview(job.id) }, enabled = !busy) { Text("AI review") }
                            TextButton(onClick = { onOpen(job.url) }) { Text("Open job") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AddJobScreen(
    company: String, setCompany: (String) -> Unit, title: String, setTitle: (String) -> Unit,
    url: String, setUrl: (String) -> Unit, location: String, setLocation: (String) -> Unit,
    description: String, setDescription: (String) -> Unit, busy: Boolean, onAdd: () -> Unit
) {
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Add a job posting. The backend will score it against your saved profile.")
        OutlinedTextField(company, setCompany, label = { Text("Company") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(title, setTitle, label = { Text("Job title") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(url, setUrl, label = { Text("Job URL (https://…)") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(location, setLocation, label = { Text("Location") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(description, setDescription, label = { Text("Description") }, modifier = Modifier.fillMaxWidth(), minLines = 4)
        Button(onClick = onAdd, enabled = !busy && company.isNotBlank() && title.isNotBlank() && url.startsWith("http")) { Text("Add and score") }
    }
}

@Composable
private fun ApplicationsScreen(
    applications: List<ApplicationItem>, busy: Boolean, onRefresh: () -> Unit,
    onStatus: (Int, String) -> Unit, onOpen: (String) -> Unit
) {
    OutlinedButton(onClick = onRefresh, enabled = !busy) { Text("Refresh applications") }
    val states = listOf("READY_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER", "REJECTED_BY_COMPANY", "WITHDRAWN")
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(applications, key = { it.jobId }) { app ->
            var expanded by remember { mutableStateOf(false) }
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(app.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text("${app.company} · ${app.status}")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { onOpen(app.url) }) { Text("Open job") }
                        OutlinedButton(onClick = { expanded = true }, enabled = !busy) { Text("Update status") }
                    }
                    androidx.compose.material3.DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                        states.forEach { state -> androidx.compose.material3.DropdownMenuItem(
                            text = { Text(state.replace('_', ' ')) },
                            onClick = { expanded = false; onStatus(app.jobId, state) }
                        ) }
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    baseUrl: String, setBaseUrl: (String) -> Unit, username: String, setUsername: (String) -> Unit,
    password: String, setPassword: (String) -> Unit, busy: Boolean, onSave: () -> Unit
) {
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Backend connection", style = MaterialTheme.typography.titleLarge)
        Text("Start the Python server first. Android Emulator: http://10.0.2.2:8000. On a phone, use your computer's LAN address, such as http://192.168.1.20:8000.")
        OutlinedTextField(baseUrl, setBaseUrl, label = { Text("Backend URL") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(username, setUsername, label = { Text("HTTP Basic Auth username") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(password, setPassword, label = { Text("HTTP Basic Auth password") }, modifier = Modifier.fillMaxWidth(), singleLine = true, visualTransformation = PasswordVisualTransformation())
        Text("Password stays in memory and clears when the app process closes. Use HTTPS if connecting over a shared network; this client allows HTTP for local development.", style = MaterialTheme.typography.bodySmall)
        Button(onClick = onSave, enabled = !busy) { Text("Save URL and connect") }
    }
}
