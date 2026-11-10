// Historial de conversaciones, solo en este navegador (localStorage). El servidor no guarda
// conversaciones: cada pregunta se responde por separado y las citas se resuelven por `chunk_id`,
// que sigue funcionando aunque el documento cambie de versión o se borre (DECISIONS.md §3).
import { useCallback, useEffect, useState } from "react";

import type { QueryResult } from "./api";

export type Turn = {
  id: string;
  question: string;
  askedAt: string;
  result: QueryResult | null;
  error: { code: string; correlationId: string | null } | null;
};

export type Conversation = {
  id: string;
  title: string;
  updatedAt: string;
  turns: Turn[];
};

// Una clave por usuario y organización: en un navegador compartido, nadie ve el historial de otro,
// y las citas de una conversación solo se resuelven en la organización donde se hizo.
function storageKey(userId: string, organizationId: string): string {
  return `nortelegal.conversations.v2.${userId}.${organizationId}`;
}
// Las respuestas incluyen los fragmentos consultados; el tope mantiene el historial muy por
// debajo del límite de localStorage (unos 5 MB).
const MAX_CONVERSATIONS = 50;
const TITLE_LENGTH = 60;

function load(key: string): Conversation[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as Conversation[]) : [];
  } catch {
    // Almacenamiento bloqueado o datos dañados: se empieza sin historial.
    return [];
  }
}

function save(key: string, conversations: Conversation[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(conversations));
  } catch {
    // Sin almacenamiento la conversación sigue funcionando, solo que no se recuerda.
  }
}

function titleFor(question: string): string {
  const oneLine = question.replace(/\s+/g, " ").trim();
  return oneLine.length > TITLE_LENGTH ? `${oneLine.slice(0, TITLE_LENGTH - 1)}…` : oneLine;
}

export function newId(): string {
  return crypto.randomUUID();
}

/** La clave no cambia durante la vida del componente: la aplicación lo vuelve a montar al cambiar
 * de usuario o de organización. */
export function useConversations(userId: string, organizationId: string) {
  const [key] = useState(() => storageKey(userId, organizationId));
  const [conversations, setConversations] = useState<Conversation[]>(() => load(key));

  useEffect(() => save(key, conversations), [key, conversations]);

  /** Añade un turno terminado. Crea la conversación si todavía no existe. */
  const addTurn = useCallback((conversationId: string, turn: Turn) => {
    setConversations((previous) => {
      const existing = previous.find((conversation) => conversation.id === conversationId);
      const updated: Conversation = existing
        ? { ...existing, updatedAt: turn.askedAt, turns: [...existing.turns, turn] }
        : { id: conversationId, title: titleFor(turn.question), updatedAt: turn.askedAt, turns: [turn] };
      const others = previous.filter((conversation) => conversation.id !== conversationId);
      return [updated, ...others].slice(0, MAX_CONVERSATIONS);
    });
  }, []);

  const removeConversation = useCallback((conversationId: string) => {
    setConversations((previous) =>
      previous.filter((conversation) => conversation.id !== conversationId),
    );
  }, []);

  return { conversations, addTurn, removeConversation };
}
