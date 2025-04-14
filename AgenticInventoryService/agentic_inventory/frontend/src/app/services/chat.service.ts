import { Injectable } from "@angular/core";
import { HttpClient } from "@angular/common/http";
import { Observable, of } from "rxjs";
import { map, catchError } from "rxjs/operators";
import { environment } from "../../environments/environment";

export interface Message {
  id: string;
  content: string;
  role: "user" | "bot";
  timestamp: number;
  isStreaming?: boolean;
  metadata?: {
    tokens_consumed?: {
      input: number;
      output: number;
    };
    latency_taken?: number;
  };
}

export interface ChatSession {
  id: string;
  title: string;
  timestamp?: number;
  previewMessage?: string;
  created_at?: string;
  updated_at?: string;
  last_message?: string | null;
  message_count?: number;
}

interface ApiSession {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  last_message?: string | null;
  message_count?: number;
}

interface ApiMessage {
  id: string;
  content: string;
  role: string;
  created_at: string;
}

interface HttpErrorResponse {
  status: number;
  message: string;
  error?: unknown;
}

interface ApiMessageRequest {
  question: string;
  metadata?: Record<string, unknown>;
}

interface ApiMessageResponse {
  answer: string;
  metadata: {
    tokens_consumed: {
      input: number;
      output: number;
    };
    latency_taken: number;
  };
}

@Injectable({
  providedIn: "root",
})
export class ChatService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  getWelcomeMessage(): string {
    return "Hello! How can I assist you today?";
  }

  fetchSessions(userId: string): Observable<ChatSession[]> {
    return this.http
      .get<ApiSession[]>(`${this.apiUrl}/users/${userId}/sessions`)
      .pipe(
        catchError((error: HttpErrorResponse) => {
          console.error("Error fetching sessions:", error);
          return of([]);
        }),
        map((sessions: ApiSession[]) =>
          sessions.map((session) => ({
            id: session.id,
            title: session.title,
            timestamp: session.updated_at
              ? new Date(session.updated_at).getTime()
              : Date.now(),
            previewMessage: session.last_message || "New conversation",
            created_at: session.created_at,
            updated_at: session.updated_at,
            last_message: session.last_message,
            message_count: session.message_count,
          })),
        ),
      );
  }

  createSession(userId: string): Observable<ChatSession> {
    return this.http
      .post<ApiSession>(`${this.apiUrl}/users/${userId}/sessions`, {
        title: "New Chat",
      })
      .pipe(
        map((responseData: ApiSession) => ({
          id: responseData.id,
          title: responseData.title,
          timestamp: responseData.created_at
            ? new Date(responseData.created_at).getTime()
            : Date.now(),
          previewMessage: "How can I help you today?",
        })),
        catchError(() => {
          return of({
            id: crypto.randomUUID(),
            title: "New Chat",
            timestamp: Date.now(),
            previewMessage: "How can I help you today?",
          });
        }),
      );
  }

  fetchMessages(userId: string, sessionId: string): Observable<Message[]> {
    return this.http
      .get<
        ApiMessage[]
      >(`${this.apiUrl}/users/${userId}/sessions/${sessionId}/messages`)
      .pipe(
        map((responseData: ApiMessage[]) => {
          if (responseData.length === 0) {
            // If no messages, return welcome message
            return [
              {
                id: crypto.randomUUID(),
                content: this.getWelcomeMessage(),
                role: "bot",
                timestamp: Date.now(),
              },
            ] as Message[];
          }

          return responseData.map((msg: ApiMessage) => ({
            id: msg.id,
            content: msg.content,
            role: this.mapApiRole(msg.role),
            timestamp: msg.created_at
              ? new Date(msg.created_at).getTime()
              : Date.now(),
          })) as Message[];
        }),
        catchError(() => {
          return of([
            {
              id: crypto.randomUUID(),
              content: this.getWelcomeMessage(),
              role: "bot",
              timestamp: Date.now(),
            },
          ] as Message[]);
        }),
      );
  }

  createMessage(
    userId: string,
    sessionId: string,
    content: string,
  ): Observable<Message> {
    const request: ApiMessageRequest = {
      question: content,
      metadata: {},
    };

    return this.http
      .post<ApiMessageResponse>(
        `${this.apiUrl}/users/${userId}/sessions/${sessionId}/messages`,
        request,
      )
      .pipe(
        map(
          (response: ApiMessageResponse) =>
            ({
              id: crypto.randomUUID(), // Since API doesn't return an ID, we generate one
              content: response.answer,
              role: "bot",
              timestamp: Date.now(),
              metadata: response.metadata, // Optional: store metadata if needed
            }) as Message,
        ),
        catchError((error) => {
          console.error("Error creating message:", error);
          // Fallback for when API fails
          const fallbackMessage: Message = {
            id: crypto.randomUUID(),
            content:
              "I apologize, but I encountered an issue processing your request. Please try again later.",
            role: "bot",
            timestamp: Date.now(),
          };

          return of(fallbackMessage);
        }),
      );
  }

  deleteSession(userId: string, sessionId: string): Observable<boolean> {
    return this.http
      .delete(`${this.apiUrl}/users/${userId}/sessions/${sessionId}`)
      .pipe(
        map(() => true),
        catchError(() => of(false)),
      );
  }

  updateSessionTitle(
    userId: string,
    sessionId: string,
    title: string,
  ): Observable<ChatSession> {
    return this.http
      .patch<ApiSession>(
        `${this.apiUrl}/users/${userId}/sessions/${sessionId}`,
        { title },
      )
      .pipe(
        map(
          (session: ApiSession) =>
            ({
              id: session.id,
              title: session.title,
              timestamp: session.updated_at
                ? new Date(session.updated_at).getTime()
                : Date.now(),
              previewMessage: session.last_message || "",
              created_at: session.created_at,
              updated_at: session.updated_at,
              last_message: session.last_message,
              message_count: session.message_count,
            }) as ChatSession,
        ),
        catchError(() => {
          return of({
            id: sessionId,
            title: title,
            timestamp: Date.now(),
          } as ChatSession);
        }),
      );
  }

  // Helper method to ensure role is always 'user' or 'bot'
  private mapApiRole(role: string): "user" | "bot" {
    return role === "user" ? "user" : "bot";
  }
}
