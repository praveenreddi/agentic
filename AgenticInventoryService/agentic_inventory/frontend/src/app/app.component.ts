import { Component, OnInit, OnDestroy } from "@angular/core";
import { CommonModule } from "@angular/common";
import { RouterOutlet, Router } from "@angular/router";
import { RouterModule } from "@angular/router";
import { ThemeService } from "./services/theme.service";
import { environment } from "../environments/environment";

// MSAL imports
import { MsalService, MsalBroadcastService } from "@azure/msal-angular";
import {
  InteractionStatus,
  AuthenticationResult,
  EventMessage,
  EventType,
} from "@azure/msal-browser";
import { Subject } from "rxjs";
import { filter, takeUntil } from "rxjs/operators";

@Component({
  selector: "app-root",
  templateUrl: "./app.component.html",
  styleUrls: ["./app.component.scss"],
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterModule],
})
export class AppComponent implements OnInit, OnDestroy {
  isDarkMode = false;
  isLoggedIn = false;
  ssoEnabled = environment.enableSSO;
  userName = "Test User"; // Default value for testing
  userEmail = "";
  private readonly _destroying$ = new Subject<void>();

  constructor(
    private themeService: ThemeService,
    private router: Router,
    private authService: MsalService,
    private msalBroadcastService: MsalBroadcastService,
  ) {
    // Ensure MSAL is initialized before any other operations
    console.log("App component constructor - initializing MSAL");
    console.log("SSO enabled:", this.ssoEnabled); // Debug SSO status
  }

  async ngOnInit() {
    // Set up theme service
    this.themeService.isDarkMode$.subscribe((isDark) => {
      this.isDarkMode = isDark;
    });

    // Set up MSAL auth status handling if SSO is enabled
    if (this.ssoEnabled) {
      console.log("SSO is enabled, setting up auth handling");

      // Wait for MSAL to be initialized
      try {
        console.log("Setting up MSAL broadcast subscriptions");

        this.msalBroadcastService.inProgress$
          .pipe(
            filter(
              (status: InteractionStatus) => status === InteractionStatus.None,
            ),
            takeUntil(this._destroying$),
          )
          .subscribe(() => {
            console.log("MSAL interaction complete");
            this.setLoginDisplay();
            this.checkAndSetActiveAccount();
          });

        this.msalBroadcastService.msalSubject$
          .pipe(
            filter(
              (msg: EventMessage) => msg.eventType === EventType.LOGIN_SUCCESS,
            ),
            takeUntil(this._destroying$),
          )
          .subscribe((result: EventMessage) => {
            console.log("Login success event received");
            const payload = result.payload as AuthenticationResult;
            this.authService.instance.setActiveAccount(payload.account);
            this.setLoginDisplay();
            this.setUserInfo();
            // Ensure we navigate to the chat page after login
            this.router.navigate(["/chat"]);
          });

        // Initialize login status - check if user is already logged in
        console.log("Initializing login status");
        this.setLoginDisplay();
        this.setUserInfo();
      } catch (error) {
        console.error("Error initializing MSAL:", error);
      }
    } else {
      console.log("SSO is disabled, skipping auth setup");
      // For testing when SSO is disabled, show the test user
      this.isLoggedIn = true;
    }
  }

  setLoginDisplay() {
    try {
      const accounts = this.authService.instance.getAllAccounts();
      console.log("Found accounts:", accounts);
      this.isLoggedIn = accounts.length > 0;
      console.log(
        "User login status:",
        this.isLoggedIn,
        "Accounts:",
        accounts.length,
      );
    } catch (error) {
      console.error("Error in setLoginDisplay:", error);
      this.isLoggedIn = false;
    }
  }

  setUserInfo() {
    if (this.isLoggedIn) {
      try {
        const account =
          this.authService.instance.getActiveAccount() ||
          this.authService.instance.getAllAccounts()[0];
        console.log("Active account:", account);

        if (account) {
          this.userName = account.name || "User";
          this.userEmail = account.username || "";
          console.log("User information set:", {
            name: this.userName,
            email: this.userEmail,
          });
        } else {
          console.warn("No account found even though isLoggedIn is true");
          this.userName = "User";
        }
      } catch (error) {
        console.error("Error in setUserInfo:", error);
        this.userName = "User";
      }
    } else {
      console.log("Not logged in, no user info to set");
    }
  }

  checkAndSetActiveAccount() {
    try {
      // Find all accounts
      const accounts = this.authService.instance.getAllAccounts();
      console.log(
        "Checking active account, found:",
        accounts.length,
        "accounts",
      );

      // If there's only one account, set it as active
      if (accounts.length === 1) {
        this.authService.instance.setActiveAccount(accounts[0]);
        console.log("Set active account:", accounts[0].name);
        this.setUserInfo();
      } else if (accounts.length > 1) {
        console.log("Multiple accounts found, using first one");
        this.authService.instance.setActiveAccount(accounts[0]);
        this.setUserInfo();
      }
    } catch (error) {
      console.error("Error in checkAndSetActiveAccount:", error);
    }
  }

  logout() {
    if (this.ssoEnabled) {
      try {
        console.log("Initiating logout");
        this.authService.logoutRedirect({
          postLogoutRedirectUri: window.location.origin,
        });
      } catch (error) {
        console.error("Error during logout:", error);
        // Fallback navigation if logout fails
        this.router.navigate(["/"]);
      }
    }
  }

  ngOnDestroy(): void {
    this._destroying$.next(undefined);
    this._destroying$.complete();
  }
}
