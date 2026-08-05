package com.inventory.mobile

import android.content.Context
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.snackbar.Snackbar

class SettingsActivity : AppCompatActivity() {

    private lateinit var baseUrlInput: EditText
    private lateinit var saveButton: Button
    private lateinit var toolbar: MaterialToolbar

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        toolbar = findViewById(R.id.settingsTopBar)
        baseUrlInput = findViewById(R.id.baseUrlInput)
        saveButton = findViewById(R.id.saveSettingsButton)

        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { finish() }

        val preferences = getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
        val currentBaseUrl = preferences.getString(
            MainActivity.KEY_BASE_URL,
            MainActivity.DEFAULT_BASE_URL,
        ).orEmpty()
        baseUrlInput.setText(currentBaseUrl)

        saveButton.setOnClickListener {
            val url = baseUrlInput.text.toString().trim().trimEnd('/')
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                Snackbar.make(
                    baseUrlInput,
                    getString(R.string.invalid_base_url_message),
                    Snackbar.LENGTH_LONG,
                ).show()
                return@setOnClickListener
            }

            preferences.edit().putString(MainActivity.KEY_BASE_URL, url).apply()
            Snackbar.make(
                saveButton,
                getString(R.string.base_url_saved_message),
                Snackbar.LENGTH_LONG,
            ).show()
        }
    }
}
