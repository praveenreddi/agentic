import { Component, EventEmitter, Input, Output } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-chat-input-bar",
  templateUrl: "./chat-input-bar.component.html",
  styleUrls: ["./chat-input-bar.component.scss"],
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class ChatInputBarComponent {
  @Input() isDisabled = false;
  @Output() sendMessage = new EventEmitter<string>();

  input = "";

  constructor() {}

  handleSubmit(): void {
    if (this.input.trim() && !this.isDisabled) {
      this.sendMessage.emit(this.input.trim());
      this.input = "";
    }
  }
}
