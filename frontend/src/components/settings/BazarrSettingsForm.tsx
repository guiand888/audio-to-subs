import { useState } from "react"
import { Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/api"
import { toast } from "sonner"
import type { SettingsPatch } from "@/lib/types"

export interface BazarrSettingsFormProps {
  formData: Partial<SettingsPatch>
  onChange: (updates: Partial<SettingsPatch>) => void
}

export function BazarrSettingsForm({
  formData,
  onChange,
}: BazarrSettingsFormProps) {
  const [testConnectionStatus, setTestConnectionStatus] = useState<
    "idle" | "testing" | "success" | "error"
  >("idle")

  const handleNumberChange = (field: keyof SettingsPatch) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    // An emptied field means "no override", not zero - a timeout/interval of
    // 0 would make every request fail (or poll) instantly.
    if (value === "") {
      onChange({ [field]: undefined })
      return
    }
    const num = parseFloat(value)
    if (!isNaN(num)) {
      onChange({ [field]: num })
    }
  }

  const handleBooleanChange = (field: keyof SettingsPatch) => (checked: boolean) => {
    onChange({ [field]: checked })
  }

  const failTestConnection = (message: string) => {
    setTestConnectionStatus("error")
    toast.error("Failed to connect to Bazarr: " + message)
    setTimeout(() => setTestConnectionStatus("idle"), 5000)
  }

  const handleTestConnection = async () => {
    setTestConnectionStatus("testing")
    try {
      // No bazarr_timeout here: the backend always uses its own short,
      // fixed timeout for this probe rather than the configured/edited
      // Bazarr Timeout setting (which is for real sync/poll requests and
      // can be much longer than we want to wait for a quick test).
      const response = await api.post<{ success: boolean; message: string | null; error: string | null }>(
        "/api/settings/test-bazarr-connection",
        {
          bazarr_url: formData.bazarr_url,
          bazarr_api_key: formData.bazarr_api_key,
        }
      )
      if (response.success) {
        setTestConnectionStatus("success")
        toast.success(response.message || "Connected to Bazarr successfully")
        setTimeout(() => setTestConnectionStatus("idle"), 3000)
      } else {
        failTestConnection(response.error || "Unknown error")
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown error"
      failTestConnection(errorMessage)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="bazarr-url">Bazarr API URL</Label>
        <Input
          id="bazarr-url"
          type="url"
          placeholder="http://bazarr:6767"
          value={formData.bazarr_url ?? ""}
          onChange={(e) => onChange({ bazarr_url: e.target.value })}
        />
        <p className="text-sm text-muted-foreground">
          Base URL for Bazarr API (e.g., http://bazarr:6767)
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="bazarr-api-key">API Key</Label>
        <Input
          id="bazarr-api-key"
          type="password"
          placeholder="Enter your Bazarr API key"
          value={formData.bazarr_api_key ?? ""}
          onChange={(e) => onChange({ bazarr_api_key: e.target.value })}
        />
        <p className="text-sm text-muted-foreground">
          Bazarr API key for authentication
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="bazarr-timeout">API Timeout (seconds)</Label>
        <Input
          id="bazarr-timeout"
          type="number"
          min="1"
          max="300"
          step="0.1"
          placeholder="30"
          value={formData.bazarr_timeout ?? ""}
          onChange={handleNumberChange("bazarr_timeout")}
        />
        <p className="text-sm text-muted-foreground">
          Timeout for real Bazarr sync/poll requests (1-300 seconds). Not used
          by Test Connection, which always uses its own short fixed timeout.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="poll-interval">Poll Interval (seconds)</Label>
        <Input
          id="poll-interval"
          type="number"
          min="0"
          placeholder="3600"
          value={formData.bazarr_poll_interval ?? ""}
          onChange={handleNumberChange("bazarr_poll_interval")}
        />
        <p className="text-sm text-muted-foreground">
          How often to poll Bazarr for new items missing subtitles.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <Label htmlFor="track-no-subs">Track Items with No Subtitles</Label>
          <p className="text-sm text-muted-foreground">
            Include items that have no subtitles in any language.
          </p>
        </div>
        <Switch
          id="track-no-subs"
          checked={formData.bazarr_track_no_subs ?? false}
          onCheckedChange={handleBooleanChange("bazarr_track_no_subs")}
        />
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!formData.bazarr_url || testConnectionStatus === "testing"}
          onClick={handleTestConnection}
        >
          {testConnectionStatus === "testing" ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Testing...
            </>
          ) : (
            "Test Connection"
          )}
        </Button>
        {testConnectionStatus === "success" && (
          <Check className="h-4 w-4 text-green-500" />
        )}
        {testConnectionStatus === "error" && (
          <span className="text-sm text-destructive">Connection failed</span>
        )}
      </div>
    </div>
  )
}
