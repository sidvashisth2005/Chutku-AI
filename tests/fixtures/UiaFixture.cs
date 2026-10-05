using System;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;

public static class UiaFixture {
    [STAThread] public static void Main() {
        var app = new Application();
        var window = new Window { Title = "Chutku UIA Fixture", Width = 520, Height = 420,
                                  WindowStartupLocation = WindowStartupLocation.CenterScreen };
        AutomationProperties.SetAutomationId(window, "FixtureWindow");
        var root = new DockPanel(); window.Content = root;
        var menu = new Menu(); DockPanel.SetDock(menu, Dock.Top);
        AutomationProperties.SetAutomationId(menu, "MainMenu");
        var actions = new MenuItem { Header = "Actions" };
        AutomationProperties.SetAutomationId(actions, "ActionsMenu");
        var run = new MenuItem { Header = "Run verified menu action" };
        AutomationProperties.SetAutomationId(run, "RunMenuItem"); actions.Items.Add(run); menu.Items.Add(actions);
        root.Children.Add(menu);
        var panel = new StackPanel { Margin = new Thickness(24) }; root.Children.Add(panel);
        var input = new TextBox { Height = 28, Margin = new Thickness(0, 0, 0, 12) };
        AutomationProperties.SetAutomationId(input, "InputField"); panel.Children.Add(input);
        var click = new Button { Content = "Verified mouse target", Height = 30, Margin = new Thickness(0, 0, 0, 12) };
        AutomationProperties.SetAutomationId(click, "ClickButton"); panel.Children.Add(click);
        var list = new ListBox { Height = 220 };
        AutomationProperties.SetAutomationId(list, "ChoiceList");
        for (int i = 0; i < 100; i++) list.Items.Add(i == 1 ? "Beta" : "Item " + i.ToString("D3"));
        panel.Children.Add(list);
        var status = new TextBlock { Text = "Idle", Margin = new Thickness(0, 12, 0, 0) };
        AutomationProperties.SetAutomationId(status, "StatusLabel"); panel.Children.Add(status);
        run.Click += (sender, eventArgs) => status.Text = "Menu invoked";
        click.Click += (sender, eventArgs) => status.Text = "Mouse clicked";
        app.Run(window);
    }
}
