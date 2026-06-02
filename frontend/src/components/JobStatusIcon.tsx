// Status indicators use icons + text, not coloured pills, per the design spec.

import {
  CheckCircle,
  Clock,
  Loader2,
  XCircle,
  AlertCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { JobStatus } from "@/lib/types"

interface JobStatusIconProps {
  status: JobStatus | string
  className?: string
}

const statusConfig: Record<
  string,
  { icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  queued: { icon: Clock, label: "Queued" },
  running: { icon: Loader2, label: "Running" },
  done: { icon: CheckCircle, label: "Done" },
  failed: { icon: XCircle, label: "Failed" },
  cancelled: { icon: AlertCircle, label: "Cancelled" },
}

export function JobStatusIcon({ status, className }: JobStatusIconProps) {
  const cfg = statusConfig[status] ?? statusConfig.queued
  const Icon = cfg.icon
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm", className)}>
      <Icon
        className={cn(
          "h-4 w-4",
          status === "running" && "animate-spin",
        )}
      />
      <span>{cfg.label}</span>
    </span>
  )
}
