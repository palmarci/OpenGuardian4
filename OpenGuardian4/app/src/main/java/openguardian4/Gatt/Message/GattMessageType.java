package openguardian4.Gatt.Message;

import openguardian4.Gatt.Converters.*;
import openguardian4.Gatt.Converters.Concrete.AlgorithmDataConverter;
import openguardian4.Gatt.Converters.Concrete.CgmMeasurementListConverter;
import openguardian4.Gatt.Converters.Concrete.ConnectionActiveParamsConverter;

public enum GattMessageType {
    ConnectionActiveParams("5f0b2420-be34-11e4-bc62-0002a5d5c51b", new ConnectionActiveParamsConverter()),
    AlgorithmData("00000205-0000-1000-0000-009132591325", new AlgorithmDataConverter()),
    CgmMeasurementList("00002aa7-0000-1000-8000-00805f9b34fb", new CgmMeasurementListConverter())
   
   
    ; public final String uuid;
    public final AbstractMessageConverter converter;

    private GattMessageType(String uuid, AbstractMessageConverter converter) {
        this.uuid = uuid;
        this.converter = converter;
    }
}
