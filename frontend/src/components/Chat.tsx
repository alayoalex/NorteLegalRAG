import { useEffect, useRef, useState } from "react";

import type { Conversation, Turn } from "../conversations";
import { errorMessage } from "../messages";
import { Answer } from "./Answer";
import { Icon } from "./Icon";

const MIN_QUESTION = 3;

type Props = {
  conversation: Conversation | null;
  pendingQuestion: string | null;
  readyDocuments: number;
  onAsk: (question: string) => void;
};

export function Chat({ conversation, pendingQuestion, readyDocuments, onAsk }: Props) {
  const turns = conversation?.turns ?? [];
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length, pendingQuestion]);

  const isEmpty = turns.length === 0 && pendingQuestion === null;

  return (
    <section className="chat" aria-label="Conversación">
      <div className="thread">
        {isEmpty ? (
          <EmptyState readyDocuments={readyDocuments} />
        ) : (
          <>
            {turns.map((turn) => (
              <TurnView key={turn.id} turn={turn} />
            ))}
            {pendingQuestion !== null && (
              <article className="turn">
                <p className="question">{pendingQuestion}</p>
                <p className="thinking" aria-live="polite">
                  Buscando en tus documentos y redactando la respuesta. Puede tardar unos segundos.
                </p>
              </article>
            )}
          </>
        )}
        <div ref={endRef} />
      </div>
      <Composer
        key={conversation?.id ?? "new"}
        busy={pendingQuestion !== null}
        onAsk={onAsk}
      />
    </section>
  );
}

function EmptyState({ readyDocuments }: { readyDocuments: number }) {
  return (
    <div className="empty">
      <h1 className="empty-title">¿Qué quieres saber de tus contratos?</h1>
      <p className="empty-detail">
        {readyDocuments === 0
          ? "Sube un contrato o una política en el panel de documentos para empezar."
          : `Responderé con citas literales de ${readyDocuments === 1 ? "tu documento" : `tus ${readyDocuments} documentos`}. Si no encuentro la respuesta, te lo diré.`}
      </p>
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  return (
    <article className="turn">
      <p className="question">{turn.question}</p>
      {turn.result && <Answer result={turn.result} />}
      {turn.error && (
        <p role="alert" className="alert">
          {errorMessage(turn.error.code)}
          {turn.error.correlationId && ` Referencia: ${turn.error.correlationId}`}
        </p>
      )}
    </article>
  );
}

function Composer({ busy, onAsk }: { busy: boolean; onAsk: (question: string) => void }) {
  const [question, setQuestion] = useState("");
  const trimmed = question.trim();
  const canSend = !busy && trimmed.length >= MIN_QUESTION;

  function send() {
    if (!canSend) return;
    onAsk(trimmed);
    setQuestion("");
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <div className="composer-box">
        <label htmlFor="question" className="visually-hidden">
          Pregunta
        </label>
        <textarea
          id="question"
          rows={2}
          maxLength={2000}
          placeholder="Por ejemplo: ¿con cuánto preaviso se puede rescindir el contrato?"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            // Enter envía, Mayús+Enter añade una línea.
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" className="send-button" disabled={!canSend} aria-label="Preguntar">
          <Icon name="send" />
        </button>
      </div>
      <p className="composer-note">
        Cada pregunta se responde por separado, solo con tus documentos.
      </p>
    </form>
  );
}
