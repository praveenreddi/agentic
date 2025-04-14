import { Component, EventEmitter, Input, OnInit, Output } from "@angular/core";
import { CommonModule } from "@angular/common";
import { ThemeService } from "../../services/theme.service";
import { MsalService } from "@azure/msal-angular";
import { environment } from "../../../environments/environment";

@Component({
  selector: "app-chat-header",
  templateUrl: "./chat-header.component.html",
  styleUrls: ["./chat-header.component.scss"],
  standalone: true,
  imports: [CommonModule],
})
export class ChatHeaderComponent implements OnInit {
  @Input() isPanelOpen = false;
  @Input() isPanelCollapsed = true;

  @Output() toggleHistory = new EventEmitter<void>();
  @Output() togglePanelCollapse = new EventEmitter<void>();
  @Output() toggleSettings = new EventEmitter<void>();

  userName = "";

  constructor(
    private themeService: ThemeService,
    private authService: MsalService,
  ) {}

  ngOnInit(): void {
    this.getUserName();
  }

  getUserName(): void {
    if (environment.enableSSO) {
      try {
        const accounts = this.authService.instance.getAllAccounts();
        if (accounts.length > 0) {
          const account =
            this.authService.instance.getActiveAccount() || accounts[0];
          if (account) {
            this.userName = account.name || "User";
          }
        }
      } catch (error) {
        console.error("Error getting user name in chat header:", error);
        this.userName = "User";
      }
    } else {
      this.userName = "User";
    }
  }

  onToggleHistory(): void {
    this.toggleHistory.emit();
  }

  onTogglePanelCollapse(): void {
    this.togglePanelCollapse.emit();
  }
}
