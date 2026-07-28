# Facebook Login Best Practices



Facebook Login improves your app user experience by enabling customers to easily sign up for your app without creating a username/password, and it maximizes the number of people using your app.

With more people using your app, you’ll see improved performance with our other business tools that are designed to provide you with insight into your audience. When more of your customers use Facebook Login, these tools are more powerful to help you understand and grow your business.
We recommend using the following best practices to maximize the number of visitors who sign up with Facebook Login. A high quality onboarding experience can lead to conversion rates above 80%.

## Video

## Checklists &#123;#best-practices&#125;

**User Experience Best Practices**

1. [Offer Facebook Login and account creation opportunities immediately](#accountcreation)
2. [Use a large, rectangular button in a consistent style with the rest of your app](#button)
3. [Keep the option to Login with Facebook visible during alternate account creation flows](#visible)
4. [Offer customers a bonus for signing in](#bonus)
5. [Minimize the choices offered](#minimizechoices)
6. [Help people avoid duplicate multi-channel accounts](#duplicate)
7. [Avoid in-app web views](#webviews)
8. [Provide a way to log out](#logout)

**Data Use Best Practices**

1.  [Only ask for the permissions you need.](#onlyask)
2.  [Ask for permissions in context and explain why.](#context)
**Warning:** [Understand Automatic App Event Logging and change the setting as needed.](https://developers.facebook.com/docs/app-events/automatic-event-collection-detail)

3.  [If you don&#039;t use the Facebook SDKs, regularly check whether the access token is valid](#checktokenvalidity).
4.  [If data access for someone has expired, put them through the reauthorization flow](#reauthflow).

**Technical Practices**

1.  [Test and measure.](#testing)
2.  [Follow the Facebook Developer Policies.](#policies)
3. [Implement a Data Deletion Callback](#datadeletion)
4. [Submit your app for App Review.](#loginreview)

**Additional Best Practices**

1. [Prompt people to log back into your app or website](#promptrelogin)
2. [Check to make sure a user access token is still valid](#checktoken)
3. [Check for revoked permissions](#revokedpermissions)
4. [Provide people with data control](#datacontrol)

## User Experience Best Practices &#123;#user-experience&#125;

#### 1. Offer Login and Account Creation Opportunities Immediately &#123;#accountcreation&#125;

A majority of users who sign into apps with Facebook do so in the first five minutes of using the app, and more than 90% do so in the first day. Promote sign in as early as possible during your first-launch experience and offer incentives that share the business value you can provide from knowing who they are.
Offering Facebook Login immediately on your welcome screen lets motivated visitors get started fast.

If your analytics show that users arrive ready to complete a task immediately, use a banner to remind them to create an account, or offer account creation a way to speed up a check-out process.

#### 2. Design: Use a Large, Rectangular Button &#123;#button&#125;

Use large, rectangular buttons for Facebook Login that are adjacent to other sign options. Facebook Login will do better if it is shown ahead of other options. You also want buttons to be consistent with the rest of your app design as buttons that are significantly visually different (for example, small, round buttons) won&#039;t perform as well.

The Facebook Login button that comes with our [SDKs](https://developers.facebook.com/docs#apis-and-sdks) is easy to integrate and includes built-in education that ensures a consistent design and experience. However, if you do decide to build your own, for best results follow the [Developer Policies for Login](https://developers.facebook.com/devpolicy#login) and the recommendations in [User Experience Design](https://developers.facebook.com/documentation/facebook-login/userexperience).

#### 3. Keep the option to Login with Facebook Visible During Alternate Account Creation Flows &#123;#visible&#125;

Customers might start down another account creation path and decide it is too much trouble if you require them to create a new password, upload a profile picture or manually enter other data they could provide through Facebook Login. Keep the option to use Facebook Login visible on these screens to convert visitors who might otherwise abandon account creation at this point.

#### 4. Offer customers a bonus for signing in &#123;#bonus&#125;

Offer customers a bonus for using Facebook Login and make it clear by the placement of your offer that it applies to Facebook Login, as well email and password sign up. You can also offer additional benefits for Facebook Login specifically.

#### 5. Minimize the choices offered &#123;#minimizechoices&#125;

If an app has too many sign in options, the conversion towards Facebook Login can decrease.  If your app supports multiple sign in options, use signals like language and country code to de-prioritize or hide options that are region specific.

#### 6. Help people avoid duplicate multi-channel accounts &#123;#duplicate&#125;

Sometimes users forget how they signed up for your service. If a user tries to use an email address to sign up or sign in and you&#039;ve seen it before with Facebook Login, remind them and give them the chance to continue with their existing account.
Ask for the same set of baseline permissions on all platforms, otherwise returning users may interpret being asked to grant a new permission as creating a new connection to Facebook, instead of easily logging back in with their existing one.

#### 7. Avoid in-app web views &#123;#webviews&#125;

On modern iOS and Android, in-app web views can&#039;t share cookies with the system browser. Because this makes it look to Facebook like a brand new browser, your visitors will see a “login to Facebook” screen with a cookie consent banner and requesting their username and password.

On Android, log in users with the native Facebook app if it is present, or a Chrome Custom Tab if not. This ensures that people who&#039;ve used Facebook on their device before are just one click away from approving your app.
Our latest iOS SDKs always prefer `ASWebAuthenticationSession` / `SFAuthenticationSession` web views that can access system cookies.

Generally, using the latest Facebook SDKs will give you the optimal behavior automatically. If you have a custom login flow or you use an integrator platform that provides Facebook Login as one of several sign in methods, make sure that your app has a Facebook Login experience that is full screen, and that you see the “use Facebook.com to Sign In” system prompt on iOS. If you see cookie consent banners or non-full screen experiences, contact your integrator and ask them to use the appropriate methods on each platform to give your visitors the best experience.

#### 8. Provide a way to log out &#123;#logout&#125;

Once people are logged in, you should also give them a way to log out, disconnect their account, or delete it all together. In addition to being a courtesy, this is also a requirement of our [Developer Policies for Login](https://developers.facebook.com/devpolicy#login).

The dating app Tinder, for example, gives you the option to log out or to delete your account entirely.

## Data Use Best Practices

#### 1. Only ask for the permissions you need &#123;#onlyask&#125;

Only ask for the [permissions](https://developers.facebook.com/documentation/facebook-login/guides/permissions) you need. The fewer permissions you ask for, the easier it is for people to feel comfortable granting them. We&#039;ve seen that asking for fewer permissions typically results in greater conversion.

You can always ask for additional permissions later after people have had a chance to try out your app.

An additional benefit of asking for fewer permissions is that you might not need to submit your app for [App Review](https://developers.facebook.com/docs/facebook-login/review). You need to submit for App Review if you request any permissions other than the default fields and email.

#### 2. Ask for permissions in context and explain why &#123;#context&#125;

You should trigger permission requests when people are trying to accomplish an action in your app which requires that specific permission.

For example, the Facebook app only asks for Location Services when people explicitly tap on the location button when updating their status.

In addition, people are most likely to accept permission requests when they clearly understand why your app needs that info to offer a better experience.

#### 3. If you don&#039;t use the Facebook SDKs, regularly check whether the access token is valid &#123;#checktokenvalidity&#125;

Although access tokens have a scheduled expiration, tokens can be caused to expire early for security reasons. If you don&#039;t use the Facebook SDKs in your app, it is extremely important that you manually implement frequent checks of the token validity — at least daily — to ensure that your app is not relying on a token that has expired early for security reasons.

#### 4. If data access for someone has expired, put them through the reauthorization flow &#123;#reauthflow&#125;  

## Technical Practices

#### 1. Test and measure &#123;#testing&#125;

It&#039;s incredibly important to test your Facebook Login flow under a variety of conditions, and we&#039;ve built a [robust testing plan](https://developers.facebook.com/documentation/facebook-login/guides/test) for you to follow. It&#039;s also a good idea to run qualitative usability tests to understand how people are reacting to what they see.

Once you&#039;ve tested your Facebook Login flow and are ready to launch, we suggest using an analytics program to understand if people are completing the process and their overall conversion rates. Best practice apps can see conversion rates of over 80%.

#### 2. Follow the Facebook Developer Policies &#123;#policies&#125;

To avoid potential problems later on, do a quick check to make sure your Facebook Login integration adheres to the [Developer Policies for Login](https://developers.facebook.com/devpolicy#login).

#### 3. Implement a Data Deletion Callback &#123;#datadeletion&#125;

To give people control of their data, implement a [data deletion callback](https://developers.facebook.com/docs/apps/delete-data) to respond to people&#039;s requests to delete data your app has from Facebook about them.

#### 4. Submit your app for App Review &#123;#loginreview&#125;

You only need to submit your app for App Review if you&#039;re requesting permissions beyond the default fields and `email`. We recommend you submit your app for review as early as possible in your development lifecycle after you&#039;ve integrated Facebook Login. You&#039;ll receive transparent feedback during the App Review process, including feedback on changes you can make to get a denied permission approved, if appropriate. For existing apps, going through Login Review will not affect your current app.

You can learn more about App Review in [App Review for Facebook Login](https://developers.facebook.com/docs/apps/review/login).

## Additional Best Practices &#123;#additional&#125;

We’re [rolling out a feature](http://newsroom.fb.com/news/2019/08/off-facebook-activity/) that gives people more transparency and control over the data other apps and websites share with us. As this feature rolls out, [it may impact Facebook Login](https://developers.facebook.com/blog/post/2019/08/20/developer-best-practices-facebook-login/).

To help developers prepare for the launch of this feature, we’re providing our developer community with these additional best practices and guidance.

#### 1. Prompt people to log back into your app or website &#123;#promptrelogin&#125;

When someone exercises control via the feature and wants to log back in to an app or website, that person should be prompted to do so when they open the app or website again. If they choose to log back in using Facebook Login, they will need to re-authorize any applicable permissions to the app or website.

#### 2. Check to make sure a user access token is still valid &#123;#checktoken&#125;

In addition, when a person logged in with Facebook Login is actively using an app or website, developers should check that the user access token is still valid by making an API call or by checking permissions. Be sure to log the user out when their access token is invalidated.

#### 3. Check for revoked permissions &#123;#revokedpermissions&#125;

People can revoke permissions granted to your app in Facebook&#039;s interface at any time after they have logged in. It is important to [check what permissions are granted to apps and websites](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke#checking) by active users.

#### 4. Provide people with data control &#123;#datacontrol&#125;

To give people control of their data, you should [implement a data deletion](https://developers.facebook.com/docs/apps/delete-data) callback to respond to people’s requests to delete data an app or website has from Facebook about them.
