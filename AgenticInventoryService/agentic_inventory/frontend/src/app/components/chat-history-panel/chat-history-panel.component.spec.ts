import { ComponentFixture, TestBed } from "@angular/core/testing";

import { ChatHistoryPanelComponent } from "./chat-history-panel.component";

describe("ChatHistoryPanelComponent", () => {
  let component: ChatHistoryPanelComponent;
  let fixture: ComponentFixture<ChatHistoryPanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatHistoryPanelComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatHistoryPanelComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it("should create", () => {
    expect(component).toBeTruthy();
  });
});
