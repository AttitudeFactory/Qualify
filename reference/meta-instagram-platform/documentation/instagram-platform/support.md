# Meta Developer Site Status, Support, and Tools



Get the status of the Meta Developer Platform APIs, explore available Meta Developer Tools, and find Support.

At the top of all pages on Meta&#039;s Developer Documentation site, the following tabs are available:

* **Apps** – The Meta App Dashboard to configure your app with Meta&#039;s APIs, products, and SDKs
* **Docs** – The documentation for implementing Meta&#039;s APIs, products, and SDKs
* **Required actions** – The required actions needed for your app to retain access to Meta&#039;s APIs
* **Support** – The support resources to ask questions, report bugs, and monitor platform status
* **Tools** – The tools for testing, debugging, and previewing during development

## Apps

The App Dashboard allows you to configure settings that may be required by the use cases, APIs, and SDKs that your app will use. It displays basic information about all apps for which you have a role and allows you to configure your app with Meta&#039;s APIs, products, and SDKs. The dashboard allows you to:

* Create and manage your app&#039;s name and Meta ID
* View the business connected to an app, if any
* View the role you have on an app
* View the published status of an app

* View and access the required actions for an app
* Create a test app for an existing app
* Remove yourself from an app
* Archive or delete apps you own

Click **Apps** at the top of the page to access the App Dashboard.

## Docs

Read the Meta Developer Documentation to learn the basics of how to send and receive data from the Meta social graph and how to implement the APIs, platforms, products, and SDKs to fit your application needs.

Click **Docs** at the top of the page to access the landing page for all available developer documentation.

## Required actions

View the actions you are required to perform for all apps you own or administer to retain access to Meta&#039;s servers, such as Data Use Checkup. You can filter actions by app name, status, and business portfolio.

Click **Required actions** at the top of the page to view any actions you need to take.

## Support

View platform health, report and view bugs, and get help with issues you encounter while developing with Meta.

Click **Support** at the top of the page to get support or view platform status.

### Support

If the platform status is reporting no issues but you are experiencing a problem, report and monitor bugs that are affecting you. Get help with **Engineering**, **Business and Ads Management**, **App Compliance**, and your **Personal Account**, and search for a topic, view trending bug reports, and trending developer documentation.

### Bugs

View current bug reports, search bug reports, and file a bug report.

### Community

Visit Meta&#039;s Developer Community Forum to ask, answer, and review questions from fellow developers.

### FAQ

Visit Meta&#039;s Frequently Asked Questions (FAQs) to find answers to common questions.

### Platform Status

Meta provides a health status page for each of the following:

* Business tools – Ads Manager, Catalog, Shops, and more
* Developer platform – Facebook Login, ads APIs, business messaging APIs, and more
* Transparency tools – Ads and Data transparency tools

Each status page allows you to view the current health of a product, tool, or API.

* A checkmark within a green circle – The service is operational with no known issues
* An exclamation within a yellow triangle – The service is recovering from disruptions or is experiencing partial disruptions
* A dash within a red stop sign – The service is currently down or experiencing major disruptions

Click the chevron to the right of an API or product to view more information.

#### View History

Click the **View History** button at the bottom of the page to see any issues that have occurred in the last 90 days. This allows you to see when an issue occurred, its duration, and status.

#### RSS Feed

Click the **RSS Feed** button at the bottom of the page to sign up for real-time status notifications for each platform or tool you care about.

### Business messaging status

Get additional information for business messaging APIs, including current and historical data for availability and latency.

#### Availability

The availability of an API or tool is shown as a percentage and is calculated by subtracting the downtime, in minutes, from the measured time period, in minutes, divided by the measured time period, in minutes then multiplied by 100.

Percent availability

=

(
Total minutes - Number of minutes the issue occurred ) /  Total minutes

X

100

For example, if the time period is 30 days (43200 minutes) and an issue occurred for 23 hours (1380 minutes) during those 30 days, the API was available for 96.81% of the time during those 30 days.

96.81% = ( 43200 - 1380 ) / 43200 X  100

#### Latency

Latency is calculated for inbound and outbound messages.

* **Inbound** –  Time from when a message is received from a user to when Meta makes the first attempt to send a corresponding message webhook to the business’s callback URL
* **Outbound** – Time from when Meta receives a send message request from a business to when the message is ready to be transmitted to the user

##### Latency Percentiles

The status page displays P90 and P99 latency percentiles:

* **P90** – 90% of requests are faster than this value
* **P99** – 99% of requests are faster than this value; only 1% are slower

## Tools

Use the various developer tools from Meta to test, debug, and upgrade the various APIs, products, and SDKs. Meta Developer tools include:

* The Graph API Explorer – Create, test, and authenticate API calls and get code
* Sharing Debugger – Preview how content will look when it&#039;s shared to Facebook
* Access Token Debugger – View details about access tokens, such as scope, type, and expiry

This page also has links to business tools such as:

* The Ads Manager – Create, preview, and publish ad campaigns
* The Business Manager – View and manage your business portfolios and assets
* The Monetization Manager – View your ads&#039; performance for each business portfolio

Click **Tools** at the top of the page to get a list of developer tools and links to them.

