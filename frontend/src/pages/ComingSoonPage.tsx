// M5 placeholder — rendered for /history, /logs, /settings

interface ComingSoonPageProps {
  page: string
}

export function ComingSoonPage({ page }: ComingSoonPageProps) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="text-center space-y-2">
        <h2 className="text-lg font-semibold">{page}</h2>
        <p className="text-sm text-muted-foreground">
          Coming in M5.
        </p>
      </div>
    </div>
  )
}
