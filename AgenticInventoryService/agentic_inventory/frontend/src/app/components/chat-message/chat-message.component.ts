import {
  Component,
  EventEmitter,
  Input,
  Output,
  ElementRef,
  ViewChild,
} from "@angular/core";
import { CommonModule } from "@angular/common";
import { Message } from "../../services/chat.service";

@Component({
  selector: "app-chat-message",
  templateUrl: "./chat-message.component.html",
  styleUrls: ["./chat-message.component.scss"],
  standalone: true,
  imports: [CommonModule],
})
export class ChatMessageComponent {
  @Input() message!: Message;
  @Output() regenerate = new EventEmitter<void>();
  @Output() delete = new EventEmitter<string>();
  @ViewChild("messageContent") messageContent!: ElementRef;

  showActions = false;

  constructor() {}

  onRegenerate(): void {
    this.regenerate.emit();
  }

  onDelete(): void {
    this.delete.emit(this.message.id);
  }

  onCopyToClipboard(content: string): void {
    navigator.clipboard
      .writeText(content)
      .then(() => {
        // Optional: Show a toast or notification that content was copied
        console.log("Content copied to clipboard");
      })
      .catch((err) => {
        console.error("Could not copy text: ", err);
      });
  }

  toggleActions(): void {
    this.showActions = !this.showActions;
  }
}
