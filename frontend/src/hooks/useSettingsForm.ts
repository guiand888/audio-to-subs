import { useState, useMemo } from "react"
import type { SettingsOut, SettingsPatch } from "@/lib/types"

/**
 * Hook to manage settings form state with generic dirty field tracking.
 * Automatically tracks which fields have changed from the original settings.
 */
export function useSettingsForm(settings: SettingsOut | undefined) {
  const [formData, setFormData] = useState<Partial<SettingsPatch>>({})

  // Sync form data with fetched settings on mount/update
  const isInitialized = useMemo(() => {
    if (settings && Object.keys(formData).length === 0) {
      setFormData({
        mistral_model: settings.mistral_model,
        mistral_rate_usd_per_minute: settings.mistral_rate_usd_per_minute,
        mistral_input_token_rate_usd: settings.mistral_input_token_rate_usd,
        mistral_output_token_rate_usd: settings.mistral_output_token_rate_usd,
        bazarr_poll_interval: settings.bazarr_poll_interval,
        bazarr_track_no_subs: settings.bazarr_track_no_subs,
        bazarr_url: settings.bazarr_url || "",
        bazarr_api_key: settings.bazarr_api_key || "",
        bazarr_timeout: settings.bazarr_timeout,
        path_mappings: settings.path_mappings as any,
        default_language: settings.default_language,
        default_output_format: settings.default_output_format,
        movies_root_path: settings.movies_root_path || "",
        tv_root_path: settings.tv_root_path || "",
        subtitles_same_directory: settings.subtitles_same_directory ?? true,
      })
    }
    return settings ? true : false
  }, [settings, formData])

  // Generic dirty field tracker: count fields that differ from original settings
  const changeCount = useMemo(() => {
    if (!settings) return 0

    const fieldNames: Array<keyof SettingsPatch> = [
      "mistral_model",
      "mistral_rate_usd_per_minute",
      "mistral_input_token_rate_usd",
      "mistral_output_token_rate_usd",
      "bazarr_poll_interval",
      "bazarr_track_no_subs",
      "bazarr_url",
      "bazarr_api_key",
      "bazarr_timeout",
      "default_language",
      "default_output_format",
      "movies_root_path",
      "tv_root_path",
      "subtitles_same_directory",
    ]

    let count = 0

    for (const field of fieldNames) {
      const formValue = formData[field]
      const settingsValue = settings[field as keyof SettingsOut]

      // Normalize empty strings to undefined/original value for bazarr fields
      // (empty string is explicit "disable" signal)
      const normalizeValue = (v: unknown) => {
        if (v === "" && (field === "bazarr_url" || field === "bazarr_api_key")) {
          return v
        }
        return v ?? (field.includes("bazarr") || field.includes("root_path") ? "" : undefined)
      }

      if (normalizeValue(formValue) !== normalizeValue(settingsValue)) {
        count++
      }
    }

    // Check path_mappings separately (requires deep comparison)
    const formPathMappings = formData.path_mappings as Array<{ from: string; to: string }> | undefined
    const settingsPathMappings = settings.path_mappings || []
    if (JSON.stringify(formPathMappings || []) !== JSON.stringify(settingsPathMappings)) {
      count++
    }

    return count
  }, [formData, settings])

  const updateFormData = (updates: Partial<SettingsPatch>) => {
    setFormData((prev) => ({ ...prev, ...updates }))
  }

  return {
    formData,
    setFormData,
    updateFormData,
    changeCount,
    isInitialized,
  }
}
