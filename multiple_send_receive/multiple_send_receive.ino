/// this code is to send/receive multiple float variables to/from Simulink
//Copyrights for Bilal A. Mubdir

typedef union{
  float number;
  uint8_t bytes[4];
} FLOATUNION_t;

// Create the variables you want to receive
FLOATUNION_t myValue1;
FLOATUNION_t myValue2;
FLOATUNION_t myValue3;

// Create the variables to send
FLOATUNION_t send1;
FLOATUNION_t send2;
FLOATUNION_t send3;

void setup() {
  // initialize serial, use the same boudrate in the Simulink Config block
  Serial.begin(115200);

}
void loop(){

  // Get the floats from serial
  getFloat();
  send1.number = myValue1.number;
  send2.number = myValue2.number;
  send3.number = myValue3.number;
  
  // Print header: Important to avoid sync errors!
  Serial.write('A'); 
  // Print float data
  for (int i=0; i<4; i++){
    Serial.write(send1.bytes[i]); 
  }
  for (int i=0; i<4; i++){
    Serial.write(send2.bytes[i]); 
  }
  for (int i=0; i<4; i++){
    Serial.write(send3.bytes[i]); 
  }
  // Print terminator
  Serial.print('\n');
 // Use the same delay in the Serial Receive block
  delay(50);
}


// Frame: 'x' + 3 x float32 + '\n'. A frame is only accepted when both the
// header and the terminator line up; otherwise slide one byte and resync, so
// line noise or a dropped byte never commits corrupted values.
const uint8_t FRAME_LEN = 14;
uint8_t rxBuf[FRAME_LEN];
uint8_t rxLen = 0;

void getFloat(){
    while (Serial.available() > 0){
      uint8_t b = (uint8_t)Serial.read();
      if (rxLen == 0 && b != 'x') continue;
      rxBuf[rxLen++] = b;
      if (rxLen < FRAME_LEN) continue;
      if (rxBuf[FRAME_LEN - 1] == '\n'){
        for (int i = 0; i < 4; i++){
          myValue1.bytes[i] = rxBuf[1 + i];
          myValue2.bytes[i] = rxBuf[5 + i];
          myValue3.bytes[i] = rxBuf[9 + i];
        }
        rxLen = 0;
      } else {
        // drop the false header, restart from the next 'x' in the window
        uint8_t j = 1;
        while (j < FRAME_LEN && rxBuf[j] != 'x') j++;
        rxLen = FRAME_LEN - j;
        memmove(rxBuf, rxBuf + j, rxLen);
      }
    }
}
