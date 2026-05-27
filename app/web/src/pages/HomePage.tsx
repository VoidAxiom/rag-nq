import { Link } from 'react-router'

export function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col justify-center gap-4 px-6 py-12">
      <p className="text-sm font-medium text-muted-foreground">rag-nq showcase</p>
      <h1 className="text-3xl font-semibold tracking-normal">Evaluation workspace</h1>
      <Link
        className="w-fit rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        to="/scoreboard"
      >
        Open scoreboard
      </Link>
    </main>
  )
}
