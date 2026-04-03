I need to make improvements for this vacation scheduler.

The purpose of this application is to act as a schedule to know doctors scheduled for vacation. This is guaranteed vacation that they have off. It should be an all inclusive sweet that has an administrator that is able to manage the schedule and multiple users that can log in. The users will log in and either manually choose the dates off that they want, sign up for those dates, and then this update in real time so that everyone can see which dates have been signed up by which physicians. There's only a certain number of slots available for each physician to sign up for. A physician can only sign up for themself and one slot can only hold one physician. Currently there are sign up buttons for the physician to add themselves for certain dates. 

There needs to be separate logins for Each user and separate login for the administrator. The administrator can edit all of slots as needed. However the each user can only edit their own vacation schedule. In other words Dr A would not be able to add or remove Dr B. Dr A would only be able to add and remove Dr A. However there should be an option for a doctor to designate another doctor to make changes to their schedule if they want. For example Dr B could designate Dr A to make changes to Dr B's schedule. 

There should be a password reset feature. It should send an email From my gmail, gmittendorf+VLCalendar@gmail.com. I have created this "+VLCalendar" alias for this reason. This email can send the password reset as needed.

The admin dashboard should allow a feature to create new users, emails, etc, and email them Notifying that they have had a new user created for them. 

There should also be a feature for Adding a vacation Request via a call to a large language model. I can use my zen API key to help make choices. The user would free text into the text field, or even dictate, if that is supported, and then it would be sent to the LLM, and then the LLM would interpret it and format it into a way that the web application could understand and then do web application would assign the physician for those dates on the VL calendar if they are open. Of course if there are conflicts or not enough open spaces, then the web application should let you know. In fact it might be even more helpful if it were to send that error back to the LLM and then the LLM could answer the reason why it was not allowed in more natural speech than a prewritten phrase that the web application might have responded with.

Everything on the site should be fully integrated with each other. All the features should inter-relate and work seemlessly.

Always use playwright to test this web application to ensure it works from a user standpoint.

As one year turns into the next year, it should be able to Recognize the best placement for the holiday vacations. In general you can use the following rules.
The Thanksgiving holiday is the four days of Thursday, friday, saturday, Sunday.
The Christmas holiday is Dec 23,24,25,26
The New Years holiday is Dec 30,31 Jan 1,2
Memorial day holiday Is three days and includes Saturday, Sunday, Monday for whatever that memorial holiday is.
July 4 Will include Saturday and Sunday if July 4th happens to fall on a Monday or a Friday. Otherwise the July 4th holiday is just the single date Tuesday Wednesday or Thursday.
Labor Day will include Saturday Sunday and Monday.
That said, the administrator should have a way to assign which dates are defined holiday dates. Note that these holiday dates are not dates that users can sign up to be put on vacation for. They should remain blank And unable to sign up for them. If a user tries to sign up for them, there should be some sort of Indication that says that they can't sign up for it because it's a holiday.

I have included copies of old and current vacation calendars for your reference. They are included in legacy VL calendar folder. Please add these to the web application in a way that can be navigated to previous years As well as viewing the current year.

Make sure to save the schedule into a local database. I think Sqlite should be fine.

There should also be a Section where physicians can what holiday they are scheduled to Have guaranteed off. Please see the holiday rotation schedule in the legacy VL calendar folder To see how it is structured. Note each year, the schedule advances by one rotation. Meaning that all the doctors who are scheduled off for The Christmas Vacation, we'll then get the New Year's vacation off the next year. same thing for Thanksgiving, it advances to Xmas, etc. Each year, when there is a new year, the holiday rotation schedule should create a new year, so It updates accordingly with the year changes. And it should show about two years into the future. 

There should be a feature where physicians can trade holidays with other physicians. For example, Dr A volunteer to trade their Christmas off with Dr B's Thanksgiving off. In this case Dr A would be able to Offer this trade to Dr B and then Dr B would accept it. And then that trade would be reflected on the holiday rotation schedule. 

of note there are three major holidays. And there are three minor holidays. The three major holidays are Christmas New Year's Thanksgiving. And The Three minor holidays are Memorial Day, July 4th, and Labor Day. This should be taken into account when developing the holiday rotation portion of the Web application

Everything should be logged appropriately. Two logs, one that logs all the changes, and another log that logs absolutely every little detail that was changed. These should be viewable on the admin console.

On the admin console, there should also be a feature to display a table and also to export a csv of all the physicians with their VL dates. the dates along the top row, and the physicians in alphabetical order along the left column. and each cell of the table (or csv) would have the text "VL".

Create an instruction page on how to use this web application. This should be for the users. It should also be for the administrators. You can use playwright to take photos of the website to make it more helpful as needed. You can even use animated GIF-type images or something else as needed if that's helpful too as well

also add a simple easter egg game if someone types in the konami code up up down down left right left right b a enter into the keyboard it displays a break-out game where you break the current vacation request cells. if you win it displays a message, "Congradulations! You beat the Emergency Department. You may retire now. :)"