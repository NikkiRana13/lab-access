#include <LiquidCrystal.h>

LiquidCrystal lcd(8, 9, 4, 5, 6, 7);

// ==================== BUTTONS ====================

#define BTN_RIGHT  0
#define BTN_UP     1
#define BTN_DOWN   2
#define BTN_LEFT   3
#define BTN_SELECT 4
#define BTN_NONE   5

// ==================== STATES ====================

enum State {
  IDLE,
  ENTER_ID,
  CHOOSE_ACTION
};

State currentState = IDLE;

// ==================== LAB ====================

int currentCapacity = 0;
const int maxCapacity = 20;

// Periodic status heartbeat - lets the Python backend stay in sync with
// this board's actual capacity even if it wasn't listening for the last
// CHECK_IN/CHECK_OUT event (e.g. it just (re)connected).
unsigned long lastStatusSentAt = 0;
const unsigned long STATUS_INTERVAL_MS = 3000;

String enteredID = "";

// Valid demo student IDs
String validIDs[] = {
  "1234",
  "4321",
  "1122",
  "3142"
};

const int numberOfValidIDs = 4;

// ==================== SESSION TRACKING ====================

// Store whether each student is currently inside
bool studentInside[] = {
  false,
  false,
  false,
  false
};

// Store check-in time for each student
unsigned long checkInTimes[] = {
  0,
  0,
  0,
  0
};


// ==========================================================
// READ BUTTON
// ==========================================================

int readButton() {

  int value = analogRead(A0);

  if (value < 50)   return BTN_RIGHT;
  if (value < 195)  return BTN_UP;
  if (value < 380)  return BTN_DOWN;
  if (value < 555)  return BTN_LEFT;
  if (value < 790)  return BTN_SELECT;

  return BTN_NONE;
}


// ==========================================================
// FIND STUDENT
// Returns their position in validIDs
// ==========================================================

int findStudent(String id) {

  for (int i = 0; i < numberOfValidIDs; i++) {

    if (id == validIDs[i]) {
      return i;
    }

  }

  return -1;
}


// ==========================================================
// HOME SCREEN
// ==========================================================

void showHome() {

  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("LAB CAP: ");
  lcd.print(currentCapacity);
  lcd.print("/");
  lcd.print(maxCapacity);

  lcd.setCursor(0, 1);
  lcd.print("Approach...");
}


// ==========================================================
// STUDENT ID SCREEN
// ==========================================================

void showIDScreen() {

  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("Enter Student ID");

  lcd.setCursor(0, 1);
  lcd.print(enteredID);
}


// ==========================================================
// CHECK-IN LOG
// ==========================================================

void logCheckIn(String studentID) {

  Serial.println();
  Serial.println("==================================================");

  Serial.print("Student ");
  Serial.print(studentID);
  Serial.println(" checked in for their lab.");

  Serial.print("Current lab capacity: ");
  Serial.print(currentCapacity);
  Serial.print("/");
  Serial.println(maxCapacity);

  Serial.println("==================================================");
  Serial.println();

  // ------------------------------------------------------------------
  // MACHINE-READABLE LINE FOR THE PYTHON BACKEND
  // The decorative block above is just for humans watching the Serial
  // Monitor - the Flask backend actually parses this one line:
  //   CHECK_IN,<student_id>,<current_capacity>
  // ------------------------------------------------------------------
  Serial.print("CHECK_IN,");
  Serial.print(studentID);
  Serial.print(",");
  Serial.println(currentCapacity);
}


// ==========================================================
// CHECK-OUT LOG
// ==========================================================

void logCheckOut(String studentID, unsigned long duration) {

  unsigned long totalSeconds = duration / 1000;

  unsigned long hours = totalSeconds / 3600;

  unsigned long minutes =
      (totalSeconds % 3600) / 60;

  unsigned long seconds =
      totalSeconds % 60;


  Serial.println();
  Serial.println("==================================================");

  Serial.print("Student ");
  Serial.print(studentID);
  Serial.println(" has finished their lab section.");

  Serial.print("Lab duration: ");

  if (hours > 0) {
    Serial.print(hours);
    Serial.print(" hr ");
  }

  Serial.print(minutes);
  Serial.print(" min ");

  Serial.print(seconds);
  Serial.println(" sec");

  Serial.print("Current lab capacity: ");
  Serial.print(currentCapacity);
  Serial.print("/");
  Serial.println(maxCapacity);

  Serial.println("==================================================");
  Serial.println();

  // ------------------------------------------------------------------
  // MACHINE-READABLE LINE FOR THE PYTHON BACKEND
  //   CHECK_OUT,<student_id>,<current_capacity>,<session_duration_seconds>
  // The Arduino owns the session duration (it measured it with millis());
  // the Python backend supplies the wall-clock timestamp for the log.
  // ------------------------------------------------------------------
  Serial.print("CHECK_OUT,");
  Serial.print(studentID);
  Serial.print(",");
  Serial.print(currentCapacity);
  Serial.print(",");
  Serial.println(totalSeconds);
}


// ==========================================================
// SETUP
// ==========================================================

void setup() {

  Serial.begin(9600);

  lcd.begin(16, 2);

  showHome();

  Serial.println();
  Serial.println("LAB ACCESS SYSTEM ONLINE");
  Serial.println("Waiting for students...");
}


// ==========================================================
// MAIN LOOP
// ==========================================================

void loop() {

  // Send a status heartbeat every few seconds, independent of button
  // presses, so the Python backend always knows the real capacity.
  unsigned long now = millis();
  if (now - lastStatusSentAt >= STATUS_INTERVAL_MS) {
    lastStatusSentAt = now;
    Serial.print("STATUS,");
    Serial.println(currentCapacity);
  }

  int button = readButton();


  // ========================================================
  // IDLE
  // ========================================================

  if (currentState == IDLE) {

    // RIGHT currently simulates the distance sensor
    if (button == BTN_RIGHT) {

      lcd.clear();

      lcd.setCursor(0, 0);
      lcd.print("Student detected");

      lcd.setCursor(0, 1);
      lcd.print("Capacity: ");
      lcd.print(currentCapacity);

      delay(1200);

      enteredID = "";

      currentState = ENTER_ID;

      showIDScreen();

      delay(300);
    }
  }


  // ========================================================
  // ENTER STUDENT ID
  // ========================================================

  else if (currentState == ENTER_ID) {

    char digit = '\0';

    // Button → number
    if (button == BTN_UP)
      digit = '1';

    else if (button == BTN_DOWN)
      digit = '2';

    else if (button == BTN_LEFT)
      digit = '3';

    else if (button == BTN_RIGHT)
      digit = '4';


    // Add digit to ID
    if (digit != '\0') {

      if (enteredID.length() < 8) {

        enteredID += digit;

        showIDScreen();
      }

      delay(300);
    }


    // SELECT = submit
    if (button == BTN_SELECT) {

      lcd.clear();

      lcd.setCursor(0, 0);
      lcd.print("Checking ID...");

      delay(700);

      int studentIndex = findStudent(enteredID);


      // VALID STUDENT
      if (studentIndex != -1) {

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("1-IN   2-OUT");

        lcd.setCursor(0, 1);
        lcd.print("Choose action");

        currentState = CHOOSE_ACTION;
      }


      // INVALID STUDENT
      else {

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("ACCESS DENIED");

        lcd.setCursor(0, 1);
        lcd.print("Invalid ID");

        Serial.println();
        Serial.print("ACCESS DENIED: Unknown student ID ");
        Serial.println(enteredID);

        delay(2000);

        enteredID = "";

        showIDScreen();
      }

      delay(300);
    }
  }


  // ========================================================
  // CHOOSE CHECK-IN / CHECK-OUT
  // ========================================================

  else if (currentState == CHOOSE_ACTION) {

    int studentIndex = findStudent(enteredID);


    // ======================================================
    // UP = 1 = CHECK IN
    // ======================================================

    if (button == BTN_UP) {

      // Student is already checked in
      if (studentInside[studentIndex]) {

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("ALREADY INSIDE");

        lcd.setCursor(0, 1);
        lcd.print("Check out first");

        delay(2000);
      }


      // Lab is full
      else if (currentCapacity >= maxCapacity) {

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("LAB FULL");

        lcd.setCursor(0, 1);
        lcd.print("Access denied");

        delay(2000);
      }


      // Successful check in
      else {

        studentInside[studentIndex] = true;

        // Remember exactly when they entered
        checkInTimes[studentIndex] = millis();

        currentCapacity++;


        // -------- LOG EVENT --------

        logCheckIn(enteredID);


        // -------- LCD --------

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("ACCESS GRANTED");

        lcd.setCursor(0, 1);
        lcd.print("Camera active");

        delay(1500);


        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("DOOR UNLOCKED");

        lcd.setCursor(0, 1);
        lcd.print("Capacity: ");
        lcd.print(currentCapacity);
        lcd.print("/");
        lcd.print(maxCapacity);

        delay(2000);
      }


      currentState = IDLE;

      showHome();

      delay(300);
    }


    // ======================================================
    // DOWN = 2 = CHECK OUT
    // ======================================================

    else if (button == BTN_DOWN) {


      // Student isn't actually checked in
      if (!studentInside[studentIndex]) {

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("NOT CHECKED IN");

        lcd.setCursor(0, 1);
        lcd.print("Cannot checkout");

        Serial.println();
        Serial.print("CHECK-OUT DENIED: Student ");
        Serial.print(enteredID);
        Serial.println(" is not currently checked in.");

        delay(2000);
      }


      // Successful checkout
      else {

        // Calculate lab duration
        unsigned long duration =
            millis() - checkInTimes[studentIndex];

        studentInside[studentIndex] = false;

        checkInTimes[studentIndex] = 0;

        if (currentCapacity > 0) {
          currentCapacity--;
        }


        // -------- LOG EVENT --------

        logCheckOut(enteredID, duration);


        // -------- LCD --------

        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("CHECKED OUT");

        lcd.setCursor(0, 1);
        lcd.print("Session complete");

        delay(1500);


        lcd.clear();

        lcd.setCursor(0, 0);
        lcd.print("LAB TIME:");

        lcd.setCursor(0, 1);

        unsigned long totalSeconds =
            duration / 1000;

        unsigned long minutes =
            totalSeconds / 60;

        unsigned long seconds =
            totalSeconds % 60;

        lcd.print(minutes);
        lcd.print("m ");
        lcd.print(seconds);
        lcd.print("s");

        delay(2500);
      }


      currentState = IDLE;

      showHome();

      delay(300);
    }
  }
}
