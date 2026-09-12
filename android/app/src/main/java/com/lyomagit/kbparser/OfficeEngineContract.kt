package com.lyomagit.kbparser

import android.content.Context
import android.content.Intent
import android.net.Uri

object OfficeEngineContract {
    const val COMPANION_PACKAGE = "com.lyomagit.kbparser.officeengine"
    const val ACTION_CONVERT = "com.lyomagit.kbparser.officeengine.CONVERT"
    const val EXTRA_SOURCE_URI = "source_uri"
    const val EXTRA_SOURCE_NAME = "source_name"
    const val EXTRA_TARGET_FORMAT = "target_format"
    const val EXTRA_RESULT_JSON = "result_json"
    const val EXTRA_RESULT_URI = "result_uri"
    const val EXTRA_RESULT_FORMAT = "result_format"

    val supportedInputMimeTypes = arrayOf(
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
        "application/rtf",
        "text/rtf",
    )

    fun buildConvertIntent(sourceUri: Uri, sourceName: String, targetFormat: String): Intent =
        Intent(ACTION_CONVERT).apply {
            setPackage(COMPANION_PACKAGE)
            data = sourceUri
            putExtra(EXTRA_SOURCE_URI, sourceUri.toString())
            putExtra(EXTRA_SOURCE_NAME, sourceName)
            putExtra(EXTRA_TARGET_FORMAT, targetFormat)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }

    fun isAvailable(context: Context): Boolean =
        Intent(ACTION_CONVERT)
            .setPackage(COMPANION_PACKAGE)
            .resolveActivity(context.packageManager) != null

    fun isCompanionFormat(mimeType: String?, fileName: String): Boolean {
        val normalizedMime = mimeType?.lowercase()
        if (normalizedMime in supportedInputMimeTypes) return true
        val extension = fileName.substringAfterLast('.', missingDelimiterValue = "").lowercase()
        return extension in setOf("doc", "docx", "pdf", "rtf")
    }

    fun targetFormatFor(fileName: String): String {
        return when (sourceFormatFor(fileName)) {
            "doc", "rtf" -> "docx"
            "pdf" -> "pdf"
            else -> sourceFormatFor(fileName).ifEmpty { "docx" }
        }
    }

    fun sourceFormatFor(fileName: String, mimeType: String? = null): String {
        val extension = fileName.substringAfterLast('.', missingDelimiterValue = "").lowercase()
        if (extension.isNotEmpty()) return extension
        return when (mimeType?.lowercase()) {
            "application/msword" -> "doc"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document" -> "docx"
            "application/pdf" -> "pdf"
            "application/rtf", "text/rtf" -> "rtf"
            else -> ""
        }
    }
}
