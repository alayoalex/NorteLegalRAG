import { DocumentList } from "./components/DocumentList";
import { QuestionForm } from "./components/QuestionForm";
import { UploadForm } from "./components/UploadForm";

export function App() {
  return (
    <main>
      <header>
        <h1>NorteLegal</h1>
        <p className="muted">Asistente de conocimiento para contratos y políticas.</p>
      </header>
      <QuestionForm />
      <UploadForm />
      <DocumentList />
    </main>
  );
}
