import { CommonModule } from "@angular/common";
import { Component, EventEmitter, Output } from "@angular/core";

@Component({
  selector: "app-settings-button",
  templateUrl: "./settings-button.component.html",
  styleUrls: ["./settings-button.component.scss"],
  standalone: true,
  imports: [CommonModule],
})
export class SettingsButtonComponent {
  @Output() click = new EventEmitter<void>();

  constructor() {}

  onClick(): void {
    this.click.emit();
  }
}
