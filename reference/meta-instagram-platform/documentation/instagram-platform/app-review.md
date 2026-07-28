# App Review for Instagram API



Your app must complete App Review before it can request permissions with Advanced Access from any app user and features with Advanced Access are active for all app users.

## Development scenarios

The following table contains the possible development scenarios and the corresponding App Review requirements.

| Development scenario | Login type | Access level | App Review |
| --- | --- | --- | --- |
| My app is only for a business I own or manage. | No login or Instagram Login | Standard Access | Not required |
| My app is only for a business I own or manage. | No login or Facebook Login | Standard Access | Not required |
| I am a Tech Provider and my app serves multiple businesses. | Instagram Login | Advanced Access | **Required** |
| I am a Tech Provider and my app serves multiple businesses. | Facebook Login | Advanced Access | **Required** |

## Available permissions &amp; features

The permissions and features you can request Advanced Access for are dependent on the login type.

**Warning:** Your app can either use Facebook Login or Instagram Login but not both.

#### [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-login-for-instagram)

* Human Agent
* Instagram Public Content Access
* `ads_management`
* `business_management`
* `catalog_management`
* `instagram_basic`
* `instagram_branded_content_ads_brand`
* `instagram_branded_content_brand`
* `instagram_branded_content_creator`
* `instagram_content_publishing`
* `instagram_manage_comments`
* `instagram_manage_events`
* `instagram_manage_insights`
* `instagram_manage_messages`
* `instagram_manage_upcoming_events`
* `instagram_shopping_tag_products`
* `pages_read_engagement`
* `pages_show_list`

#### [Instagram API with Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)

* Human Agent
* `instagram_business_basic`
* `instagram_business_content_publishing`
* `instagram_business_manage_comments`
* `instagram_business_manage_messages`

### Migrated apps

If you are migrating your app to Instagram API with Instagram Login from Instagram API with Facebook Login, your app might automatically be granted Advanced Access for the corresponding Instagram API permission and App Review isn&#039;t required.

If your app is not automatically granted Advanced Access, then you will need to submit for App Review.

| [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-login-for-instagram) | [Instagram API with Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) |
| --- | --- |
| `instagram_basic` | `instagram_business_basic` |
| `instagram_content_publishing` | `instagram_business_content_publishing` |
| `instagram_manage_comments` | `instagram_business_manage_comments` |
| `instagram_manage_messages` | `instagram_business_manage_messages` |

**Warning:** If you need to submit for App Review you must follow the instructions in the [**Start a submission** section below](#start-a-submission). The submission flow in the App Dashboard has changed.

## Start a submission

To submit for App Review, go to the App Dashboard.

1. In the left-side menu under **Products**, go to **Instagram &gt; API setup with Instagram login**.
2. Click the chevron in the upper right corner of the **Complete app review** section.
3. Review the permissions and features you are requesting Advanced Access for and click **Continue to app review**.  You&#039;ll be redirected to **App Review &gt; Requests** in the dashboard.
4. Click the **Edit** button to trigger the review flow.

## Request for App Review

You will see a list of action items that are required. These include the following:

* Confirm that your app can be loaded and tested externally
* Verify that the login button or link is visible in your app and screencast, and adheres to our brand guidelines
* Provide clear use case details and describe step-by-step how a person uses your app
Tell us how your use of each permission you have requested follows established usage guidelines
* To request Advanced Access to certain permissions, you need to make at least 1 successful API call

### Complete App Settings

Add or upate your app&#039;s settings.

Click the **Review your app settings** to add or update the following:

1. App icon (1024x1024) – The icon for your app
1. Privacy Policy URL – The privacy policy URL that your app users can visit to view your privacy policy
1. App Category – The app category that best represents your app&#039;s functionality
1. Business Email – The email, set in your Developer Settings, where App Review results and developer alert emails are sent

### Complete App Verification

Provide detailed instructions for Meta app reviwers to log in and test your app.

Click **Provide verification details** to provide detailed step-by-step instructions, for each platform on which your app is available, for Meta app reviewers so they can log in to your app to test your integration and how you are using each permission and feature.

1. Platform Settings
* Provide **detailed step-by-step instructions for Meta reviewers to log in and test your app** on each platform, Android, iOS, Web, and so on, on which your app is available. Be specific about when and how your app uses each permission and feature and how a reviewer can test each usage.
1. Credentials (If applicable)
* If needed, provide any required test credentials for Meta reviewers to log into your app or website.

**NOTE:** Web or mobile Web is the only platform that currently supports Instagram API with Instagram Login.

### Permission &amp; feature requests

Provide a description for how your app uses a specific permission and include a screencast showing this usage.

Click the arrow icon to the right of each **How will your app use** question for each permission or feature  that you have requested. You will be asked to:

* Describe how your app uses that specific permission or feature
* Upload a screencast showing the end-to-end user experience for that specific permission or feature. The screencast only needs to showcase how your app is using that permission or feature.
* Agree that you will comply with the allowed usage for that permission or feature.
* If a permission or feature is dependent on another permission, you must include this permission in your submission.

**Note:** If you request permissions or features that your app does not use or does not align with the allowed usage for that permission or feature, your submission will not be approved.

### Screencast guidance

To ensure that your screen recording is accessible to all our reviewers, please follow these guidelines:

- **Use English as the app UI language** – If possible, please set the app UI language to English before recording the screen recording. This will make it easier for the review team to understand the content of your app.

- **Provide captions and tool-tips** – If your app is not available in English, or if there are any parts of the app that are not self-explanatory, please provide captions and tool-tips to explain what is happening on screen. This will help the review team understand what you are showcasing and how the app works.

- **Explain the meaning of buttons and other UI elements** – Please take the time to explain the meaning of any buttons or other UI elements that are not immediately obvious. This will help the review team understand how to use your app and what each button does.

### Completed items

When an item is complete, the circle with a check mark will be filled in.

## See Also

See the following documents to learn more about Meta App Review:

- [Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels)

- [App Development with Meta](https://developers.facebook.com/documentation/development)

- [Best Practices for Meta App Review](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/app-review/submission-guide)

- [Common Mistakes](https://developers.facebook.com/docs/app-review/submission-guide/common-mistakes)
of App Review submissions

- [Meta App Review](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/app-review)

- [Sample Submissions](https://developers.facebook.com/docs/app-review/submission-guide/screen-recordings)

