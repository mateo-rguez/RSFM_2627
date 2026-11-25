// Formateador de uplinks para la consola de TTN (opcional).
// Applications -> tu aplicación -> Payload formatters -> Uplink -> Custom Javascript.
// Solo sirve para ver los datos legibles en "Live data"; la estación
// descodifica los bytes ella misma con formato_paquete.py.
//
// Paquete común (30 bytes, big-endian):
// versión(1) seq(4) t_envio(8, double) altitud(4) acc_x(4) acc_y(4) acc_z(4) flags(1)
function decodeUplink(input) {
  var b = input.bytes;
  if (b.length !== 30) {
    return { errors: ["Se esperaban 30 bytes y llegaron " + b.length] };
  }
  var vista = new DataView(new Uint8Array(b).buffer);
  var flags = vista.getUint8(29);
  function valor(pos) {
    var v = vista.getFloat32(pos, false);
    return isNaN(v) ? null : Math.round(v * 10000) / 10000;
  }
  return {
    data: {
      version: vista.getUint8(0),
      seq: vista.getUint32(1, false),
      t_envio: vista.getFloat64(5, false),
      altitud_m: (flags & 1) ? valor(13) : null,
      acc_x: (flags & 2) ? valor(17) : null,
      acc_y: (flags & 2) ? valor(21) : null,
      acc_z: (flags & 2) ? valor(25) : null,
      simulado: (flags & 4) !== 0
    }
  };
}
