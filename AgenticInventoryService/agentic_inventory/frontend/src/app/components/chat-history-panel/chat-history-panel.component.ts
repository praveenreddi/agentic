import { Component, EventEmitter, Input, Output } from "@angular/core";
import { ChatSession } from "../../services/chat.service";
import { CommonModule } from "@angular/common";
import { SettingsButtonComponent } from "../settings-button/settings-button.component";

@Component({
  selector: "app-chat-history-panel",
  templateUrl: "./chat-history-panel.component.html",
  styleUrls: ["./chat-history-panel.component.scss"],
  standalone: true,
  imports: [CommonModule, SettingsButtonComponent],
})
export class ChatHistoryPanelComponent {
  @Input() isOpen = true;
  @Input() isCollapsed = true;
  @Input() sessions: ChatSession[] = [];
  @Input() activeSessionId: string | null = null;

  @Output() selectSession = new EventEmitter<string>();
  @Output() createNewChat = new EventEmitter<void>();
  @Output() deleteSession = new EventEmitter<string>();
  @Output() openSettings = new EventEmitter<void>();

  showDeleteConfirm = false;
  sessionToDelete: string | null = null;

  constructor() {}

  onSelectSession(sessionId: string): void {
    this.selectSession.emit(sessionId);
  }

  onCreateNewChat(): void {
    this.createNewChat.emit();
  }

  confirmDeleteSession(sessionId: string, event: MouseEvent): void {
    event.stopPropagation();
    this.sessionToDelete = sessionId;
    this.showDeleteConfirm = true;
  }

  onDeleteSession(): void {
    if (this.sessionToDelete) {
      this.deleteSession.emit(this.sessionToDelete);
      this.closeDeleteConfirm();
    }
  }

  closeDeleteConfirm(): void {
    this.showDeleteConfirm = false;
    this.sessionToDelete = null;
  }

  onOpenSettings(): void {
    this.openSettings.emit();
  }

  formatDate(timestamp?: number): string {
    if (!timestamp) return "";

    const date = new Date(timestamp);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();

    if (isToday) {
      return date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    } else {
      return date.toLocaleDateString([], { month: "short", day: "numeric" });
    }
  }
}
