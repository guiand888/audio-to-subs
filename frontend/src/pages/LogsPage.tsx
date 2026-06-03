// Logs page: global log viewer with filters and auto-refresh.
// Fetches from GET /api/logs.

import { useState, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { RefreshCw, ChevronLeft, ChevronRight } from "lucide-react"
import { format } from "date-fns"

import { api } from "@/lib/api"
import type { GlobalLogsResponse, LogsFilters, LogLevel } from "@/lib/types"

// Import from shadcn/ui
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const LEVEL_OPTIONS: { value: LogLevel; label: string; color: string }[] = [
  { value: "debug", label: "Debug", color: "text-muted-foreground" },
  { value: "info", label: "Info", color: "text-blue-600" },
  { value: "warning", label: "Warning", color: "text-yellow-600" },
  { value: "error", label: "Error", color: "text-red-600" },
]

// Get color class for log level
function getLevelColor(level: LogLevel): string {
  const option = LEVEL_OPTIONS.find((o) => o.value === level)
  return option?.color || "text-muted-foreground"
}

// Get level badge variant
function getLevelVariant(level: LogLevel): "default" | "secondary" | "destructive" | "outline" {
  switch (level) {
    case "error":
      return "destructive"
    case "warning":
      return "secondary"
    case "debug":
      return "outline"
    default:
      return "default"
  }
}

// Format timestamp
function formatTimestamp(ts: string): string {
  try {
    return format(new Date(ts), "yyyy-MM-dd HH:mm:ss")
  } catch {
    return ts
  }
}

// Filter form component
interface LogsFiltersProps {
  filters: LogsFilters
  onChange: (filters: LogsFilters) => void
}

function LogsFiltersForm({ filters, onChange }: LogsFiltersProps) {
  const [level, setLevel] = useState<LogLevel | undefined>(filters.level_filter)
  const [jobId, setJobId] = useState<string | undefined>(filters.job_id)

  const handleApply = () => {
    onChange({
      ...filters,
      level_filter: level,
      job_id: jobId || undefined,
      offset: 0,
    })
  }

  const handleReset = () => {
    setLevel(undefined)
    setJobId(undefined)
    onChange({ offset: 0 })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Filters</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="level-filter">Level</Label>
          <Select
            value={level}
            onValueChange={(v) => setLevel(v as LogLevel)}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="All levels" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All levels</SelectItem>
              {LEVEL_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  <span className={opt.color}>{opt.label}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="job-id-filter">Job ID</Label>
          <Input
            id="job-id-filter"
            type="text"
            placeholder="Filter by job ID"
            value={jobId || ""}
            onChange={(e) => setJobId(e.target.value)}
            className="w-full"
          />
        </div>

        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleReset}>
            Reset
          </Button>
          <Button size="sm" onClick={handleApply}>
            Apply
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// Main LogsPage component
export function LogsPage() {
  const [filters, setFilters] = useState<LogsFilters>({ offset: 0, limit: 50 })
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [refreshInterval] = useState(10000) // 10 seconds

  // Build query string from filters
  const params = useMemo(() => {
    const p = new URLSearchParams()
    if (filters.level_filter) p.set("level_filter", filters.level_filter)
    if (filters.job_id) p.set("job_id", filters.job_id)
    if (filters.since) p.set("since", filters.since)
    if (filters.until) p.set("until", filters.until)
    p.set("limit", String(filters.limit || 50))
    p.set("offset", String(filters.offset || 0))
    return p.toString()
  }, [filters])

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["logs", filters],
    queryFn: () => api.get<GlobalLogsResponse>(`/api/logs?${params}`),
    staleTime: 5000, // Shorter stale time for logs
    refetchInterval: autoRefresh ? refreshInterval : undefined,
  })

  const handleFiltersChange = (newFilters: LogsFilters) => {
    setFilters(newFilters)
  }

  const handleManualRefresh = () => {
    void refetch()
  }

  const toggleAutoRefresh = () => {
    setAutoRefresh(!autoRefresh)
  }

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <p>Loading logs...</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-destructive">Failed to load logs</p>
      </div>
    )
  }

  const response = data
  const logs = response?.logs || []
  const total = response?.total || 0

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Logs</h1>
          <p className="text-sm text-muted-foreground">
            System and job event logs
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleManualRefresh}
            disabled={isLoading}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button
            size="sm"
            variant={autoRefresh ? "default" : "outline"}
            onClick={toggleAutoRefresh}
          >
            Auto-refresh: {autoRefresh ? "On" : "Off"}
          </Button>
        </div>
      </div>

      <div className="flex gap-4">
        {/* Filters sidebar */}
        <div className="w-full md:w-[250px] flex-none">
          <LogsFiltersForm filters={filters} onChange={handleFiltersChange} />
        </div>

        {/* Logs table */}
        <div className="flex-1 overflow-auto">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Log Entries</CardTitle>
              <CardDescription>
                {total} total entries
              </CardDescription>
            </CardHeader>
            <CardContent>
              {logs.length === 0 ? (
                <p className="text-muted-foreground text-center py-8">
                  No logs found matching your filters
                </p>
              ) : (
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead className="p-3">Timestamp</TableHead>
                      <TableHead className="p-3">Level</TableHead>
                      <TableHead className="p-3">Job ID</TableHead>
                      <TableHead className="p-3 flex-1">Message</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {logs.map((log) => (
                      <TableRow
                        key={log.id}
                        className="border-t hover:bg-muted/50"
                      >
                        <TableCell className="p-3 whitespace-nowrap">
                          {formatTimestamp(log.ts)}
                        </TableCell>
                        <TableCell className="p-3">
                          <Badge
                            variant={getLevelVariant(log.level)}
                            className={getLevelColor(log.level)}
                          >
                            {log.level.toUpperCase()}
                          </Badge>
                        </TableCell>
                        <TableCell className="p-3 whitespace-nowrap">
                          {log.job_id ? (
                            <a
                              href={`#/queue?job_id=${log.job_id}`}
                              className="text-primary underline"
                              onClick={(e) => {
                                e.preventDefault()
                                // Could navigate to queue with filter
                              }}
                            >
                              {log.job_id.slice(0, 8)}...
                            </a>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="p-3 max-w-[400px] truncate">
                          <span className="block truncate" title={log.message}>
                            {log.message}
                          </span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}

              {/* Pagination */}
              {total > (filters.limit || 50) && (
                <div className="flex items-center justify-between pt-4">
                  <p className="text-sm text-muted-foreground">
                    Showing {(filters.offset || 0) + 1}-{Math.min(
                      (filters.offset || 0) + (filters.limit || 50),
                      total
                    )} of {total}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={filters.offset === 0}
                      onClick={() =>
                        setFilters({
                          ...filters,
                          offset: Math.max(0, (filters.offset || 0) - (filters.limit || 50)),
                        })
                      }
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        filters.offset !== undefined &&
                        filters.offset + (filters.limit || 50) >= total
                      }
                      onClick={() =>
                        setFilters({
                          ...filters,
                          offset: (filters.offset || 0) + (filters.limit || 50),
                        })
                      }
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
